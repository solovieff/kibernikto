"""TelegramAgent — KiberniktoAgent with Telegram transport (deps, preprocess, reply)."""

import asyncio
import logging
import random
import re
from collections import OrderedDict
from typing import Optional

from aiogram.enums import ChatType
from aiogram.types import Message, BufferedInputFile, ReplyParameters
from pydantic_ai.messages import BinaryContent
from kibernikto.telegram.peer_protocol import PeerEnvelope, PeerProtocolError, download_envelope, FILENAME
from pydantic_ai import AgentRunResult, ModelHTTPError, RunContext

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.kibernikto_agent import agent as kibernikto_agent
from kibernikto.ai.agent.core.kibernikto_agent import model as kibernikto_model
from kibernikto.ai.agent.core.image import generate_image
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.storage.singletons import chat_data
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from kibernikto.telegram.utils.conversation import is_private_peer_request, reply

from .chat_context import refresh_chat_context
from .deps import TelegramDeps
from .group_message import annotate_group_message
from .identity import get_bot_identity

logger = logging.getLogger(__name__)


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
            capture_peer_media: bool = False,
            **kwargs,
    ) -> None:
        kwargs.setdefault("deps_type", TelegramDeps)
        super().__init__(**kwargs)
        self._pre_processor = pre_processor or TelegramMessagePreprocessor()
        self.capture_peer_media = capture_peer_media
        self._peer_requests: OrderedDict[tuple[int, int, str], None] = OrderedDict()
        # Instructions survive history window truncation — always sent each turn.
        # Base KiberniktoAgent injects personality; here we add bot identity + per-run user/chat context.
        self.instructions(self._bot_identity_prompt)
        self.instructions(self._user_context_prompt)
        # Reusable image-generation tool: delivers its result via deps.attachments.
        if AGENT_KIBERNIKTO_SETTINGS.IMAGE_MODEL_NAME:
            self.tool(generate_image)

    async def _bot_identity_prompt(self, ctx: RunContext[TelegramDeps]) -> str:
        """Inject bot identity (getMe + descriptions) — set once at startup."""
        return get_bot_identity() or ""

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
        await refresh_chat_context(message)
        info = await chat_data.load(message.chat.id)
        deps.conversation_context = f"[Current conversation context] {info.as_string()}"
        deps.timezone = info.timezone
        return deps

    async def process_message(self, message: Message) -> AgentRunResult | PeerEnvelope | str | None:
        """Run the agent on ``message`` with per-chat history.

        Returns the :class:`AgentRunResult` on success, an error ``str`` on a
        model failure, or ``None`` when the message carried nothing to answer.
        Tools queue binaries on ``deps.attachments``; ``KiberniktoAgent.run``
        folds them into the response so :meth:`reply_to` delivers them as media.
        """
        # Bot-to-bot traffic rules:
        #  - private: only opted-in new requests; replies belong to the peer hub.
        #  - group: post flat (no reply chain) and add a random delay in
        #    [configured, 13s] so two bots talking don't spin in a loop.
        if message.from_user and message.from_user.is_bot:
            if message.chat.type == ChatType.PRIVATE and not is_private_peer_request(message):
                return None
            if message.chat.type != ChatType.PRIVATE and TELEGRAM_SETTINGS.BOT_MESSAGE_DELAY > 0:
                await asyncio.sleep(random.uniform(TELEGRAM_SETTINGS.BOT_MESSAGE_DELAY, 13.0))

        envelope = None
        captured = None
        if is_private_peer_request(message) and message.document and message.caption and message.caption.startswith('KIBERNIKTO_PEER/'):
            if message.edit_date is not None or message.from_user.id != message.chat.id or not re.fullmatch(r'KIBERNIKTO_PEER/1 request [0-9a-f]{32}', message.caption):
                return None
            key = (message.bot.id, message.from_user.id, message.caption.rsplit(' ', 1)[1])
            if key in self._peer_requests:
                return None
            self._peer_requests[key] = None
            while len(self._peer_requests) > 4096:
                self._peer_requests.popitem(last=False)
            try:
                async with asyncio.timeout(30):
                    envelope = await download_envelope(message.bot, message)
            except Exception:
                return PeerEnvelope.create('error', 'Invalid or unavailable peer input', [], request_id=key[2])
            user_message = [envelope.text, *[b for b in envelope.binaries if b.is_image]]
        elif self.capture_peer_media:
            from kibernikto.telegram.peer_inputs import capture_peer_inputs
            captured = await capture_peer_inputs(message)
            user_message = [message.text or message.caption or 'Process the attached media.',
                            *[b for b in captured if b.is_image]]
        else:
            user_message = await self._pre_processor.process_tg_message(message)
        if not user_message:
            return None

        deps = await self.build_deps(message)
        deps.user_message_parts = list(user_message)
        if envelope is not None:
            deps.peer_inputs = list(envelope.binaries)
        elif captured is not None:
            deps.peer_inputs = captured
        # Annotate group messages with author + local time so the model knows who said what.
        # Bots are identified by @username (so peers can mention them), humans by full name.
        if not deps.is_personal and (deps.user_full_name or deps.username):
            author = deps.username if message.from_user and message.from_user.is_bot else deps.user_full_name
            user_message = annotate_group_message(list(user_message), author, deps.timezone or "Europe/Moscow")
            deps.user_message_parts = list(user_message)

        try:
            result = await self.run(
                user_message, chat_id=None if envelope is not None else message.chat.id, deps=deps
            )
            if envelope is not None:
                result._peer_request_id = envelope.request_id
            return result
        except ModelHTTPError as error:
            logger.exception(error)
            if envelope is not None:
                return PeerEnvelope.create('error', 'Remote model failed', [], request_id=envelope.request_id)
            return error.message
        except Exception as error:
            logger.exception(error)
            if envelope is not None:
                return PeerEnvelope.create('error', 'Remote execution failed', [], request_id=envelope.request_id)
            return str(error)

    async def reply_to(self, message: Message, result: AgentRunResult | PeerEnvelope | str | None) -> None:
        """Send the agent's response back to the chat (no-op if ``None``).

        Delivers the model text together with any binaries tools produced,
        which ``KiberniktoAgent.run`` already folded into the response.
        """
        request_id = result.request_id if isinstance(result, PeerEnvelope) else getattr(result, '_peer_request_id', None)
        if request_id is not None and is_private_peer_request(message):
            envelope = result if isinstance(result, PeerEnvelope) else PeerEnvelope.create(
                'result', result.output, list(result.response.files), request_id=request_id)
            try:
                wire = envelope.encode()
            except PeerProtocolError:
                envelope = PeerEnvelope.create('error', 'Remote output exceeded transport limits', [], request_id=request_id)
                wire = envelope.encode()
            await message.bot.send_document(chat_id=message.chat.id,
                document=BufferedInputFile(wire, filename=FILENAME), caption=envelope.caption,
                parse_mode=None, reply_parameters=ReplyParameters(message_id=message.message_id))
            return
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
