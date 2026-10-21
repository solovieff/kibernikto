"""TelegramAgent — standard pydantic-ai Agent with Telegram transport (deps, preprocess, reply)."""

import asyncio
import logging
import random
import re
from collections import OrderedDict
from collections.abc import Sequence

from aiogram.enums import ChatType
from aiogram.types import BufferedInputFile, Message, ReplyParameters
from pydantic_ai import Agent, AgentRunResult, ModelHTTPError, ModelSettings, RunContext
from pydantic_ai.messages import UserContent

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.errors import InsufficientCreditsError, map_model_error
from kibernikto.ai.agent.core.image import generate_image
from kibernikto.ai.agent.core.persona import PersonaCapability, PersonaSource
from kibernikto.ai.agent.harness.conversation_history import ConversationHistory, is_steered
from kibernikto.ai.agent.utils import build_kibernikto_model, with_attribution
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.singletons import chat_data, history_storage
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.peer_protocol import FILENAME, PeerEnvelope, PeerProtocolError, download_envelope
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from kibernikto.telegram.utils.conversation import is_private_peer_request, reply
from kibernikto.utils.time_utils import DEFAULT_TIMEZONE

from .agent_reaction import AgentReaction
from .chat_context import get_chat_context
from .deps import TelegramDeps
from .group_message import annotate_group_message
from .identity import TelegramPersona, get_bot_identity

logger = logging.getLogger(__name__)


def user_facing_model_error(error: ModelHTTPError) -> str:
    """Chat text for a provider error; the raw body stays in logs only (see ``core.errors``)."""
    return map_model_error(error).user_message


def default_model_settings() -> ModelSettings:
    """Default model settings built from ``AGENT_KIBERNIKTO_SETTINGS``."""
    return ModelSettings(
        max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
        temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
        parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS,
    )


class TelegramAgent(Agent[TelegramDeps]):
    """An :class:`Agent` that speaks Telegram.

    Owns both ends of the conversation: :meth:`process_message` turns an
    aiogram ``Message`` into agent input and runs it with per-chat history,
    while :meth:`reply_to` renders the result back into the chat. Subclass to
    add tools or swap the :attr:`pre_processor`, then register your instance
    with :func:`set_telegram_agent` before the dispatcher starts.
    """

    def __init__(
            self,
            *,
            history_storage: HistoryStorage | None = history_storage,
            persona_source: PersonaSource | None = None,
            persona: bool = True,
            reaction: str | None = ...,
            pre_processor: TelegramMessagePreprocessor | None = None,
            capture_peer_media: bool = False,
            **kwargs,
    ) -> None:
        name = kwargs.setdefault("name", AGENT_KIBERNIKTO_SETTINGS.NAME)
        kwargs.setdefault("deps_type", TelegramDeps)
        reaction_val = AGENT_KIBERNIKTO_SETTINGS.REACTION if reaction is ... else reaction
        if "model" not in kwargs:
            kwargs["model"] = build_kibernikto_model(
                AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME,
                AGENT_KIBERNIKTO_SETTINGS.FALLBACK_MODELS,
            )
        if "model_settings" not in kwargs:
            kwargs["model_settings"] = default_model_settings()

        self._active_runs: dict[str, RunContext[TelegramDeps]] = {}
        self._history_storage = history_storage

        self._conv_history = ConversationHistory(
            history_storage,
            history_size=AGENT_KIBERNIKTO_SETTINGS.HISTORY_SIZE,
            keep_thinking=AGENT_KIBERNIKTO_SETTINGS.KEEP_THINKING_IN_HISTORY,
            active_runs=self._active_runs,
        )
        persona_cap = PersonaCapability(
            name,
            source=persona_source or self.default_persona_source(),
            include_persona=persona,
        )

        caps = [*(kwargs.get("capabilities") or ()), self._conv_history, persona_cap]
        if reaction_val is not None:
            caps.append(AgentReaction())
        kwargs["capabilities"] = caps

        if not callable(settings := kwargs.get("model_settings")):
            kwargs["model_settings"] = with_attribution(settings, name)

        kwargs["metadata"] = {**(kwargs.get("metadata") or {}), "reaction": reaction_val}
        super().__init__(**kwargs)

        self._pre_processor = pre_processor or TelegramMessagePreprocessor()
        self.capture_peer_media = capture_peer_media
        self._peer_requests: OrderedDict[tuple[int, int, str], None] = OrderedDict()

        self.instructions(self._bot_identity_prompt)
        self.instructions(self._user_context_prompt)

        if AGENT_KIBERNIKTO_SETTINGS.IMAGE_MODEL_NAME:
            self.tool(generate_image)

    @property
    def history_storage(self) -> HistoryStorage | None:
        return self._history_storage

    @staticmethod
    def default_persona_source() -> PersonaSource:
        """``{{name}}`` falls back to the Telegram bot name from getMe."""
        return TelegramPersona()

    async def _bot_identity_prompt(self, ctx: RunContext[TelegramDeps]) -> str:
        """Inject bot identity (getMe + descriptions) — fetched once at startup."""
        identity = get_bot_identity()
        return identity.as_prompt() if identity else ""

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

        Loads ``chat_data`` once into ``chat_info`` (read-only; credits) and takes
        ``conversation_context`` from the in-memory getChat cache — nothing is written.
        Override to enrich the deps further — keep ``await super().build_deps(message)``.
        """
        deps = TelegramDeps(
            is_personal=message.chat.type == ChatType.PRIVATE,
            app_chat_info=message.chat.description,
            app_chat_name=message.chat.title,
            user_id=message.from_user.id if message.from_user else None,
            username=message.from_user.username if message.from_user else None,
            user_full_name=message.from_user.full_name if message.from_user else None,
            message=message,
        )
        deps.chat_info = await chat_data.load(str(message.chat.id))
        # Credits stay out of the prompt for now; prepend them here when the model needs its balance.
        deps.conversation_context = f"[Current conversation context] {await get_chat_context(message)}"
        deps.timezone = DEFAULT_TIMEZONE
        return deps

    async def process_message(self, message: Message) -> AgentRunResult | PeerEnvelope | str | None:
        """Run the agent on ``message`` with per-conversation history.

        Returns the :class:`AgentRunResult` on success, a ``str`` when credits
        are exhausted, or ``None`` when the message carried nothing to answer
        (or was steered into an already active run for this conversation).
        Tools queue binaries on ``deps.attachments``; ``ConversationHistory``
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
            deps.billable = False
        elif captured is not None:
            deps.peer_inputs = captured
        # Annotate group messages with author + local time so the model knows who said what.
        # Bots are identified by @username (so peers can mention them), humans by full name.
        if not deps.is_personal and (deps.user_full_name or deps.username):
            author = deps.username if message.from_user and message.from_user.is_bot else deps.user_full_name
            user_message = annotate_group_message(list(user_message), author, deps.timezone or DEFAULT_TIMEZONE)
            deps.user_message_parts = list(user_message)

        cid = None if envelope is not None else str(message.chat.id)
        try:
            result = await self.run(user_message, conversation_id=cid, deps=deps)
            if is_steered(result):
                return None  # Absorbed by the live run for this chat; it replies once.
            if deps.message is not None and deps.message is not message:
                result._reply_message = deps.message
            if envelope is not None and result is not None:
                result._peer_request_id = envelope.request_id
            return result
        except Exception as error:
            if envelope is None and isinstance(error, InsufficientCreditsError):
                return str(error)
            if envelope is None:
                raise
            logger.exception(error)
            reason = 'Remote model failed' if isinstance(error, ModelHTTPError) else 'Remote execution failed'
            return PeerEnvelope.create('error', reason, [], request_id=envelope.request_id)

    async def reply_to(self, message: Message, result: AgentRunResult | PeerEnvelope | str | None) -> None:
        """Send the agent's response back to the chat (no-op if ``None``).

        Delivers the model text together with any binaries tools produced,
        which ``ConversationHistory`` already folded into the response.
        """
        target = getattr(result, '_reply_message', None) or message
        request_id = result.request_id if isinstance(result, PeerEnvelope) else getattr(result, '_peer_request_id', None)
        if request_id is not None and is_private_peer_request(target):
            envelope = result if isinstance(result, PeerEnvelope) else PeerEnvelope.create(
                'result', result.output, list(result.response.files), request_id=request_id)
            try:
                wire = envelope.encode()
            except PeerProtocolError:
                envelope = PeerEnvelope.create('error', 'Remote output exceeded transport limits', [], request_id=request_id)
                wire = envelope.encode()
            await target.bot.send_document(chat_id=target.chat.id,
                document=BufferedInputFile(wire, filename=FILENAME), caption=envelope.caption,
                parse_mode=None, reply_parameters=ReplyParameters(message_id=target.message_id))
            return
        if result is not None:
            await reply(target, result)

    def to_telegram(self):  # noqa: ANN201 — returns TelegramApp
        """Build a runnable Telegram bot wired to this agent (``to_web`` analog).

        Returns :class:`TelegramApp` — call ``.run_polling()`` to start.
        """
        from kibernikto.telegram.agent.telegram_app import TelegramApp

        return TelegramApp.from_agent(self)


_telegram_agent: TelegramAgent | None = None


def get_telegram_agent() -> TelegramAgent:
    """Return the active Telegram agent, building the default one on first call."""
    global _telegram_agent
    if _telegram_agent is None:
        _telegram_agent = TelegramAgent()
    return _telegram_agent


def set_telegram_agent(agent: TelegramAgent) -> TelegramAgent | None:
    """Swap the active agent used by the conversation handlers.

    Handlers resolve the agent at call time, so this takes effect as long as
    it runs before the dispatcher starts polling. Returns the previous agent.
    """
    global _telegram_agent
    previous, _telegram_agent = _telegram_agent, agent
    return previous
