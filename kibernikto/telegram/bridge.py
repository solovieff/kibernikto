"""TelegramBridge — aiogram I/O around a plain Agent[TelegramDeps]: deps, preprocessing, peers, replies."""

import asyncio
import logging
import random
import re
from collections import OrderedDict

from aiogram.enums import ChatType
from aiogram.types import BufferedInputFile, Message, ReplyParameters
from pydantic_ai import Agent, AgentRunResult, ModelHTTPError

from kibernikto.ai.agent.core.errors import InsufficientCreditsError, map_model_error
from kibernikto.ai.agent.harness.conversation_history import history_storage_of, is_steered
from kibernikto.ai.agent.telegram.chat_context import get_chat_context
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.group_message import annotate_group_message
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.singletons import chat_data
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.peer_protocol import FILENAME, PeerEnvelope, PeerProtocolError, download_envelope
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from kibernikto.telegram.utils.conversation import is_private_peer_request, reply
from kibernikto.utils.time_utils import DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)


def user_facing_model_error(error: ModelHTTPError) -> str:
    """Chat text for a provider error; the raw body stays in logs only (see ``core.errors``)."""
    return map_model_error(error).user_message


class TelegramBridge:
    """Feeds Telegram messages to ``agent`` and renders its results back; not an agent itself."""

    def __init__(self, agent: Agent[TelegramDeps], *,
                 pre_processor: TelegramMessagePreprocessor | None = None,
                 capture_peer_media: bool = False) -> None:
        self.agent = agent
        self.pre_processor = pre_processor or TelegramMessagePreprocessor()
        self.capture_peer_media = capture_peer_media
        self._peer_requests: OrderedDict[tuple[int, int, str], None] = OrderedDict()

    @property
    def history_storage(self) -> HistoryStorage | None:
        return history_storage_of(self.agent)

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
            user_message = await self.pre_processor.process_tg_message(message)
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
            result = await self.agent.run(user_message, conversation_id=cid, deps=deps)
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


_bridge: TelegramBridge | None = None


def get_telegram_bridge() -> TelegramBridge:
    """Active bridge; builds the default Telegram agent on first call."""
    global _bridge
    if _bridge is None:
        from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent
        _bridge = TelegramBridge(build_telegram_agent())
    return _bridge


def set_telegram_bridge(bridge: TelegramBridge) -> TelegramBridge | None:
    """Swap the bridge used by handlers; returns the previous one."""
    global _bridge
    previous, _bridge = _bridge, bridge
    return previous
