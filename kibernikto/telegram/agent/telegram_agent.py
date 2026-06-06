import logging
from dataclasses import dataclass
from typing import Optional

from aiogram.types import Message
from pydantic_ai import AgentRunResult, ModelHTTPError, WebSearchTool
from pydantic_ai.capabilities import NativeTool


from kibernikto.ai.agent import kibernikto_agent
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.image import generate_image
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from kibernikto.telegram.utils.conversation import reply

logger = logging.getLogger(__name__)


@dataclass
class TelegramDeps(KiberniktoDeps):
    """Run-scoped deps for the Telegram agent.

    Inherits the transport-agnostic side-channel (``attachments`` / ``extra``)
    from :class:`KiberniktoDeps` and adds Telegram-specific context so tools can
    react to the originating chat/user.
    """

    message: Optional[Message] = None
    chat_id: Optional[int] = None
    user_id: Optional[int] = None


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
        # Reusable image-generation tool: delivers its result via deps.attachments.
        if AGENT_KIBERNIKTO_SETTINGS.IMAGE_MODEL_NAME:
            self.tool(generate_image)

    @property
    def pre_processor(self) -> TelegramMessagePreprocessor:
        """Strategy that turns an aiogram ``Message`` into agent input."""
        return self._pre_processor

    @pre_processor.setter
    def pre_processor(self, value: TelegramMessagePreprocessor) -> None:
        self._pre_processor = value

    def build_deps(self, message: Message) -> TelegramDeps:
        """Create the run-scoped deps for ``message``.

        Override to enrich the deps (extra context, services, ...) before the
        run. Tools mutate this object in place; binaries they queue on
        ``attachments`` are folded into the response by ``KiberniktoAgent.run``.
        """
        return TelegramDeps(
            message=message,
            chat_id=message.chat.id,
            user_id=message.from_user.id if message.from_user else None,
        )

    async def process_message(self, message: Message) -> AgentRunResult | str | None:
        """Run the agent on ``message`` with per-chat history.

        Returns the :class:`AgentRunResult` on success, an error ``str`` on a
        model failure, or ``None`` when the message carried nothing to answer.
        Tools queue binaries on ``deps.attachments``; ``KiberniktoAgent.run``
        folds them into the response so :meth:`reply_to` delivers them as media.
        """
        user_message = await self._pre_processor.process_tg_message(message)
        if not user_message:
            return None

        deps = self.build_deps(message)
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


#: Default agent used by the conversation handlers, built from the same
#: env-derived config as the core ``kibernikto_agent`` singleton.
kibernikto_telegram_agent: TelegramAgent = TelegramAgent(
    model=kibernikto_agent.model,
    model_settings=kibernikto_agent.model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    system_prompt=AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I,
)


def set_telegram_agent(agent: TelegramAgent) -> TelegramAgent:
    """Swap the active agent used by the conversation handlers.

    Handlers resolve the agent at call time, so this takes effect as long as
    it runs before the dispatcher starts polling. Returns the previous agent.
    """
    global kibernikto_telegram_agent
    previous, kibernikto_telegram_agent = kibernikto_telegram_agent, agent
    return previous
