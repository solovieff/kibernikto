import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

from aiogram.enums import ChatType
from aiogram.types import Chat, ChatFullInfo, Message
from pydantic_ai import AgentRunResult, ModelHTTPError, RunContext
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.messages import UserContent

from kibernikto.ai.agent import kibernikto_agent, kibernikto_model
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.image import generate_image
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.storage.file.chat_data import chat_data
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from kibernikto.telegram.utils.conversation import reply
from kibernikto.utils.time_utils import enhance_message, get_user_time

logger = logging.getLogger(__name__)


@dataclass
class TelegramDeps(KiberniktoDeps):
    """Run-scoped deps for the Telegram agent.

    Inherits the transport-agnostic side-channel (``attachments`` / ``extra``)
    from :class:`KiberniktoDeps` and adds Telegram-specific context so tools can
    react to the originating chat/user.
    """

    is_personal: bool = True
    chat_id: Optional[int] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    user_full_name: Optional[str] = None
    app_chat_info: Optional[str] = None
    app_chat_name: Optional[str] = None
    message: Optional[Message] = None
    timezone: Optional[str] = None


# ── Chat enrichment ───────────────────────────────────────────────────────────

_CHAT_REFRESH_SECONDS = 600.0


def _format_chat_context(chat: ChatFullInfo) -> Optional[str]:
    """Compact one-line chat facts (title/description/bio/members/birthday) from a full Chat."""
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
        parts = [f"group chat in '{chat.title}'"]
        if chat.username:
            parts.append(f"username: @{chat.username}")
        if chat.description:
            parts.append(f"chat_info: {chat.description}")
        if getattr(chat, "member_count", None):
            parts.append(f"members: {chat.member_count}")
        return " | ".join(parts)
    name = " ".join(filter(None, [chat.first_name, chat.last_name])) or "unknown"
    parts = [f"private chat with {name}"]
    if chat.username:
        parts.append(f"username: @{chat.username}")
    if getattr(chat, "bio", None):
        parts.append(f"bio: {chat.bio}")
    birthdate = getattr(chat, "birthdate", None)
    if birthdate:
        bd = f"{birthdate.day:02d}.{birthdate.month:02d}"
        if getattr(birthdate, "year", None):
            bd += f".{birthdate.year}"
        parts.append(f"birthday: {bd}")
    return " | ".join(parts)


async def _refresh_chat_context(message: Message) -> None:
    """Persist full getChat facts into the chat bucket, refreshing when missing or stale."""
    info = chat_data.load(message.chat.id)
    updated_at = info.client_app_info_updated_at or 0
    if info.client_app_info and time.time() - updated_at < _CHAT_REFRESH_SECONDS:
        return
    try:
        chat = await message.bot.get_chat(message.chat.id)
    except Exception as error:
        logger.warning("Failed to fetch full chat %s: %s", message.chat.id, error)
        return
    info.client_app_info = _format_chat_context(chat) or info.client_app_info
    info.client_app_info_updated_at = time.time()
    chat_data.save(message.chat.id, info)


def _annotate_group_message(parts: list[UserContent], author: str, timezone: str) -> list[UserContent]:
    """Prefix the message with the author and local time — [{author} at {time}]."""
    stamp = f"[{author} at {get_user_time(timezone)}]"
    for i, part in enumerate(parts):
        if isinstance(part, str) and part.strip():
            parts[i] = enhance_message(part, author, timezone)
            return parts
    return [stamp, *parts]


class TelegramAgent(KiberniktoAgent):
    """A :class:`KiberniktoAgent` that speaks Telegram.

    Owns both ends of the conversation: :meth:`process_message` turns an
    aiogram ``Message`` into agent input and runs it with per-chat history,
    while :meth:`reply_to` renders the result back into the chat. Subclass to
    add tools or swap the :attr:`pre_processor`, then register your instance
    with :func:`set_telegram_agent` before the dispatcher starts.
    """

    def __init__(
            self,
            *,
            pre_processor: Optional[TelegramMessagePreprocessor] = None,
            **kwargs,
    ) -> None:
        kwargs.setdefault("deps_type", TelegramDeps)
        super().__init__(**kwargs)
        self._pre_processor = pre_processor or TelegramMessagePreprocessor()
        # Instructions survive history window truncation — always sent each turn.
        # Base KiberniktoAgent injects personality; here we add per-run user/chat context.
        self.instructions(self._user_context_prompt)
        # Reusable image-generation tool: delivers its result via deps.attachments.
        if AGENT_KIBERNIKTO_SETTINGS.IMAGE_MODEL_NAME:
            self.tool(generate_image)

    async def _user_context_prompt(self, ctx: RunContext[TelegramDeps]) -> str:
        """Inject the transport-built conversation context into the system prompt each run."""
        if not ctx.deps:
            return ""
        return ctx.deps.conversation_context or ""

    @property
    def pre_processor(self) -> TelegramMessagePreprocessor:
        """Strategy that turns an aiogram ``Message`` into agent input."""
        return self._pre_processor

    @pre_processor.setter
    def pre_processor(self, value: TelegramMessagePreprocessor) -> None:
        self._pre_processor = value

    async def build_deps(self, message: Message) -> TelegramDeps:
        """Create the run-scoped deps for ``message``, enriched with chat context.

        Refreshes the persisted per-chat facts (getChat on a TTL), then sets
        ``conversation_context`` and ``timezone`` from the bucket. Override to
        enrich the deps further — keep ``await super().build_deps(message)``.
        """
        deps = TelegramDeps(
            is_personal=message.chat.type == ChatType.PRIVATE,
            chat_id=message.chat.id,
            app_chat_info=message.chat.description,
            app_chat_name=message.chat.title,
            user_id=message.from_user.id if message.from_user else None,
            username=message.from_user.username if message.from_user else None,
            user_full_name=message.from_user.full_name if message.from_user else None,
            message=message,
        )
        await _refresh_chat_context(message)
        info = chat_data.load(message.chat.id)
        deps.conversation_context = f"[Current conversation context] {info.as_string()}"
        deps.timezone = info.timezone
        return deps

    async def process_message(self, message: Message) -> AgentRunResult | str | None:
        """Run the agent on ``message`` with per-chat history.

        Returns the :class:`AgentRunResult` on success, an error ``str`` on a
        model failure, or ``None`` when the message carried nothing to answer.
        Tools queue binaries on ``deps.attachments``; ``KiberniktoAgent.run``
        folds them into the response so :meth:`reply_to` delivers them as media.
        """
        # Bot-to-bot traffic rules:
        #  - private: nobody reads it, don't even run the model.
        #  - group: post flat (no reply chain) and add a random delay in
        #    [configured, 13s] so two bots talking don't spin in a loop.
        if message.from_user and message.from_user.is_bot:
            if message.chat.type == ChatType.PRIVATE:
                return None
            if TELEGRAM_SETTINGS.BOT_MESSAGE_DELAY > 0:
                await asyncio.sleep(random.uniform(TELEGRAM_SETTINGS.BOT_MESSAGE_DELAY, 13.0))

        user_message = await self._pre_processor.process_tg_message(message)
        if not user_message:
            return None

        deps = await self.build_deps(message)
        deps.user_message_parts = list(user_message)
        # Annotate group messages with author + local time so the model knows who said what.
        # Bots are identified by @username (so peers can mention them), humans by full name.
        if not deps.is_personal and (deps.user_full_name or deps.username):
            author = deps.username if message.from_user and message.from_user.is_bot else deps.user_full_name
            user_message = _annotate_group_message(list(user_message), author, deps.timezone or "Europe/Moscow")
            deps.user_message_parts = list(user_message)

        try:
            return await self.run(
                user_message, chat_id=message.chat.id, deps=deps
            )
        except ModelHTTPError as error:
            logger.exception(error)
            return error.message
        except Exception as error:
            logger.exception(error)
            return str(error)

    async def reply_to(self, message: Message, result: AgentRunResult | str | None) -> None:
        """Send the agent's response back to the chat (no-op if ``None``).

        Delivers the model text together with any binaries tools produced,
        which ``KiberniktoAgent.run`` already folded into the response.
        """
        if result is not None:
            await reply(message, result)

    def to_telegram(self):  # noqa: ANN201 — returns TelegramApp
        """Build a runnable Telegram bot wired to this agent (``to_web`` analog).

        Returns :class:`TelegramApp` — call ``.run_polling()`` to start.
        """
        from kibernikto.telegram.agent.telegram_app import TelegramApp
        return TelegramApp.from_agent(self)


#: Default agent used by the conversation handlers, built from the same
#: env-derived config as the core ``kibernikto_agent`` singleton.
kibernikto_telegram_agent: TelegramAgent = TelegramAgent(
    model=kibernikto_model,
    model_settings=kibernikto_agent.model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
)


def set_telegram_agent(agent: TelegramAgent) -> TelegramAgent:
    """Swap the active agent used by the conversation handlers.

    Handlers resolve the agent at call time, so this takes effect as long as
    it runs before the dispatcher starts polling. Returns the previous agent.
    """
    global kibernikto_telegram_agent
    previous, kibernikto_telegram_agent = kibernikto_telegram_agent, agent
    return previous
