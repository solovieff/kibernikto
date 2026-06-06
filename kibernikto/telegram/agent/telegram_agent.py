import logging
from typing import Optional

from aiogram.types import Message
from pydantic_ai import AgentRunResult, ModelHTTPError, WebSearchTool
from pydantic_ai.capabilities import NativeTool

from kibernikto.ai.agent import kibernikto_agent
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from kibernikto.telegram.utils.conversation import reply

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
            **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._pre_processor = pre_processor or TelegramMessagePreprocessor()

    @property
    def pre_processor(self) -> TelegramMessagePreprocessor:
        """Strategy that turns an aiogram ``Message`` into agent input."""
        return self._pre_processor

    @pre_processor.setter
    def pre_processor(self, value: TelegramMessagePreprocessor) -> None:
        self._pre_processor = value

    async def process_message(self, message: Message) -> AgentRunResult | str | None:
        """Run the agent on ``message`` with per-chat history.

        Returns the :class:`AgentRunResult` on success, the error text on a
        model failure, or ``None`` when the message carried nothing to answer.
        """
        user_message = await self._pre_processor.process_tg_message(message)
        if not user_message:
            return None

        try:
            return await self.run(user_message, chat_id=message.chat.id)
        except ModelHTTPError as error:
            logger.exception(error)
            return error.message
        except Exception as error:
            logger.exception(error)
            return str(error)

    async def reply_to(self, message: Message, result: AgentRunResult | str | None) -> None:
        """Send the agent's response back to the chat (no-op if ``None``)."""
        if result is not None:
            await reply(message, result)


#: Default agent used by the conversation handlers, built from the same
#: env-derived config as the core ``kibernikto_agent`` singleton.
kibernikto_telegram_agent: TelegramAgent = TelegramAgent(
    model=kibernikto_agent.model,
    model_settings=kibernikto_agent.model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    system_prompt=AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I,
    capabilities=[NativeTool(WebSearchTool())],
)


def set_telegram_agent(agent: TelegramAgent) -> TelegramAgent:
    """Swap the active agent used by the conversation handlers.

    Handlers resolve the agent at call time, so this takes effect as long as
    it runs before the dispatcher starts polling. Returns the previous agent.
    """
    global kibernikto_telegram_agent
    previous, kibernikto_telegram_agent = kibernikto_telegram_agent, agent
    return previous
