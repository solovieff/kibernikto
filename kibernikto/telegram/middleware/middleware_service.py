import asyncio
import logging
from typing import Dict, Any, Callable, Awaitable

from aiogram import BaseMiddleware, Dispatcher, Bot
from aiogram import enums
from aiogram.types import ErrorEvent, Message

from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.utils.permissions import is_from_admin
from .utils import get_event_message

logger = logging.getLogger(__name__)


class ServiceMiddleware(BaseMiddleware):
    """Forward every non-admin private message to the configured service group."""

    def __init__(self) -> None:
        self.service_group_id = TELEGRAM_SETTINGS.SERVICE_GROUP_ID
        if not self.service_group_id:
            raise EnvironmentError("Telegram SERVICE_GROUP_ID is not set.")

    async def __call__(
            self,
            handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
            event: Message,
            data: Dict[str, Any],
    ) -> Any:
        message: Message | None = get_event_message(event)
        if message and message.chat.type == enums.ChatType.PRIVATE:
            asyncio.create_task(self._forward(message))
        return await handler(event, data)

    async def _forward(self, message: Message) -> None:
        if is_from_admin(message):
            return  # skip admin messages — service group is for monitoring users
        try:
            await message.forward(chat_id=self.service_group_id)
        except Exception as exc:
            logger.exception("Failed to forward service message: %s", exc)

    @staticmethod
    def apply_if_needed(dispatcher: Dispatcher) -> None:
        if TELEGRAM_SETTINGS.SERVICE_GROUP_ID is not None:
            dispatcher.message.outer_middleware(ServiceMiddleware())
            logger.info(
                "service middleware: ✅ %s",
                TELEGRAM_SETTINGS.model_dump_json(indent=2, include={"SERVICE_GROUP_ID"}),
            )
        else:
            logger.info("service middleware: 💤")


class ErrorsMiddleware(BaseMiddleware):
    """Send a brief error report to the service group on any unhandled exception.

    Registered on ``dispatcher.error``, so ``event`` is an ``ErrorEvent``
    with ``.update`` (the original aiogram ``Update``) and ``.exception``.
    """

    def __init__(self) -> None:
        self.service_group_id = TELEGRAM_SETTINGS.SERVICE_GROUP_ID
        if not self.service_group_id:
            raise EnvironmentError("Telegram SERVICE_GROUP_ID is not set.")

    async def __call__(
            self,
            handler: Callable[[ErrorEvent, Dict[str, Any]], Awaitable[Any]],
            event: ErrorEvent,
            data: Dict[str, Any],
    ) -> Any:
        # First let the default error handler run.
        result = await handler(event, data)

        # Then try to report to the service group asynchronously.
        user_message: Message | None = get_event_message(event.update)
        if user_message:
            asyncio.create_task(
                self._report(bot=user_message.bot, user_message=user_message, exc=event.exception)
            )

        return result

    async def _report(self, bot: Bot, user_message: Message, exc: BaseException) -> None:
        username = getattr(user_message.from_user, "username", "unknown") or "unknown"
        text = (
            f"🔥 {username} | {user_message.content_type}\n"
            f"{user_message.md_text or ''}\n"
            f"<{type(exc).__name__}: {exc}>"
        )
        try:
            await bot.send_message(self.service_group_id, text)
        except Exception as send_exc:
            logger.exception("Failed to send error report to service group: %s", send_exc)

    @staticmethod
    def apply_if_needed(dispatcher: Dispatcher) -> None:
        if TELEGRAM_SETTINGS.SERVICE_GROUP_ID is not None:
            dispatcher.error.outer_middleware(ErrorsMiddleware())
            logger.info(
                "error middleware: ✅ %s",
                TELEGRAM_SETTINGS.model_dump_json(indent=2, include={"SERVICE_GROUP_ID"}),
            )
        else:
            logger.info("error middleware: 💤")
