import asyncio
import logging
from typing import Optional

from aiogram.types import Message
from pydantic_ai import AgentRunResult, ModelHTTPError

from kibernikto.ai.agent import kibernikto_agent
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from kibernikto.telegram.utils.conversation import reply

logger = logging.getLogger(__name__)


class TelegramAgent(KiberniktoAgent):
    """
    Kibernikto agent specialised for Telegram.

    Encapsulates the two ends of the Telegram conversation lifecycle so that the
    default conversation handlers stay as thin glue:

    * :meth:`process_message` — convert an aiogram ``Message`` into agent input
      via :attr:`pre_processor`, run the agent with per-chat history, and keep
      Telegram's "typing…" indicator alive while the model thinks. Model errors
      are caught and surfaced as plain strings.
    * :meth:`reply_to` — send the agent's result back to the chat, including any
      images / audio / video / PDFs the model emitted, with Markdown formatting
      and long-message chunking handled by the shared :func:`reply` helper.

    Subclass to add tools, customise the preprocessor, or override either
    method independently. The default conversation handlers always read the
    active agent from :data:`kibernikto_telegram_agent` at call time, so a
    project that wants to plug in its own subclass should call
    :func:`set_telegram_agent` before the dispatcher starts.

    Example::

        from kibernikto.ai.agent import kibernikto_agent
        from kibernikto.telegram.agent.telegram_agent import (
            TelegramAgent,
            set_telegram_agent,
        )
        from pydantic_ai import RunContext


        class MyAgent(TelegramAgent):
            pass


        my_agent = MyAgent(
            model=kibernikto_agent.model,
            model_settings=kibernikto_agent.model_settings,
            system_prompt="You are Kibernikto's helpful cousin.",
        )


        @my_agent.tool
        async def get_time(ctx: RunContext) -> str:
            from datetime import datetime
            return datetime.now().isoformat()


        set_telegram_agent(my_agent)
    """

    def __init__(
            self,
            *,
            pre_processor: Optional[TelegramMessagePreprocessor] = None,
            **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._pre_processor: TelegramMessagePreprocessor = (
                pre_processor or TelegramMessagePreprocessor()
        )

    # ── preprocessor accessor ──────────────────────────────────────────
    @property
    def pre_processor(self) -> TelegramMessagePreprocessor:
        """The preprocessor used to turn aiogram ``Message`` objects into
        agent input. Defaults to :class:`TelegramMessagePreprocessor`; can be
        replaced at runtime or via the ``pre_processor`` constructor kwarg."""
        return self._pre_processor

    @pre_processor.setter
    def pre_processor(self, value: TelegramMessagePreprocessor) -> None:
        self._pre_processor = value

    # ── public API ────────────────────────────────────────────────────
    async def process_message(
            self, message: Message
    ) -> AgentRunResult | str | None:
        """
        Turn an aiogram ``Message`` into agent input and run the agent.

        Steps:

        1. Preprocess the message via :attr:`pre_processor`. If the result is
           ``None`` (e.g. ignored content type, or empty content), return
           ``None`` without running the agent.
        2. Spawn a background task that re-sends the "typing" chat action
           every 4 seconds so the user sees activity while the model thinks.
        3. Run ``self.run(user_message, chat_id=message.chat.id)`` — this
           honours the per-chat history override from
           :class:`KiberniktoAgent`.
        4. Catch :class:`pydantic_ai.ModelHTTPError` and generic ``Exception``,
           converting them to plain ``str`` return values instead of raising.
        5. Always cancel the typing task before returning, awaiting its
           cancellation to avoid leaking background coroutines.

        Returns:
            ``AgentRunResult`` on success, ``str`` containing the error text
            on failure, or ``None`` if the message had nothing to process.
        """
        user_message = await self._pre_processor.process_tg_message(message)
        if not user_message:
            return None

        chat = message.chat
        bot = message.bot

        typing_task = asyncio.create_task(self._typing_loop(chat.id, bot))
        try:
            return await self.run(user_message, chat_id=chat.id)
        except ModelHTTPError as model_error:
            logger.exception(model_error)
            return model_error.message
        except Exception as exc:  # noqa: BLE001 — surface as text, not raise
            logger.exception(exc)
            return f"{exc}"
        finally:
            typing_task.cancel()
            try:
                await typing_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def reply_to(
            self,
            message: Message,
            result: AgentRunResult | str | None,
    ) -> None:
        """
        Send the agent's response back to the originating chat.

        Delegates to :func:`kibernikto.telegram.utils.conversation.reply`,
        which handles Markdown formatting, long-message chunking, and any
        images / audio / video / PDFs the model attached to its
        ``ModelResponse``.

        No-op when ``result`` is ``None``.
        """
        if result is None:
            return
        await reply(message, result)

    # ── internals ─────────────────────────────────────────────────────
    @staticmethod
    async def _typing_loop(chat_id: int, bot) -> None:
        """Send the 'typing' chat action every 4s until cancelled."""
        try:
            while True:
                await bot.send_chat_action(chat_id, "typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover — network best-effort
            logger.debug(f"typing loop ended: {e}")


# ── module-level default singleton ────────────────────────────────────
# Built from the same env-derived configuration as ``kibernikto_agent`` so
# that the default Telegram surface is a thin wrapper around the core agent.
kibernikto_telegram_agent: TelegramAgent = TelegramAgent(
    model=kibernikto_agent.model,
    model_settings=kibernikto_agent.model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    system_prompt=AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I,
)


def set_telegram_agent(agent: TelegramAgent) -> TelegramAgent:
    """
    Replace the active :class:`TelegramAgent` used by the default
    conversation handlers.

    The handlers look up :data:`kibernikto_telegram_agent` at call time, so
    calling this function before the dispatcher starts is enough to make
    the rest of the bot use ``agent``.

    Args:
        agent: A :class:`TelegramAgent` (typically a subclass) configured
            with the desired model, system prompt, tools, and preprocessor.

    Returns:
        The previous agent, so callers can keep a reference for restore /
        testing purposes.
    """
    global kibernikto_telegram_agent
    previous = kibernikto_telegram_agent
    kibernikto_telegram_agent = agent
    return previous
