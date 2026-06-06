import asyncio
import logging
from typing import Dict, Any, Callable, Awaitable

from aiogram import BaseMiddleware, Dispatcher
from aiogram import enums, Bot, Router
from aiogram.types import Message

from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.utils.permissions import is_from_admin
from .utils import get_event_message

logger = logging.getLogger(__name__)


class ServiceMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.service_group_id = TELEGRAM_SETTINGS.SERVICE_GROUP_ID
        if not self.service_group_id:
            raise EnvironmentError('Telegram Service Group ID not set')

    async def __call__(
            self,
            handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
            event: Message,
            data: Dict[str, Any]
    ) -> Any:
        message: Message = get_event_message(event)
        if message and message.chat.type == enums.ChatType.PRIVATE:
            asyncio.create_task(self.forward_message_service_group(message))
        return await handler(event, data)

    async def forward_message_service_group(self, message: Message) -> None:
        try:
            if not is_from_admin(message) or 1 == 1: # FIXME DEBUG
                await message.forward(chat_id=self.service_group_id)
        except Exception as e:
            logger.exception(f"failed to send service message {e}", exc_info=True)

    @staticmethod
    def apply_if_needed(dispatcher: Dispatcher):
        if TELEGRAM_SETTINGS.SERVICE_GROUP_ID is not None:
            middleware = ServiceMiddleware()
            dispatcher.message.outer_middleware(middleware)
            logger.info(
                f"logging middleware: ✅ {TELEGRAM_SETTINGS.model_dump_json(indent=2, include={'SERVICE_GROUP_ID'})}")
        else:
            logger.info(f"logging middleware: 💤")


class ErrorsMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.service_group_id = TELEGRAM_SETTINGS.SERVICE_GROUP_ID
        if not self.service_group_id:
            raise EnvironmentError('Telegram Service Group ID not set')

    async def __call__(
            self,
            handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
            event: Message,
            data: Dict[str, Any]
    ) -> Any:
        user_message: Message = get_event_message(event)
        if not user_message:
            return await handler(event, data)

        service_message = f"🔥🔥🔥 {user_message.from_user.username} {user_message.content_type}: {user_message.md_text} {event.exception}"
        asyncio.create_task(self.send_message_to_service_group(bot=user_message.bot, service_message=service_message))

        return await handler(event, data)

    async def send_message_to_service_group(self, bot: Bot, service_message: str) -> None:
        try:
            await bot.send_message(self.service_group_id, service_message)
        except Exception as e:
            logger.exception(f"failed to send service message {e}", exc_info=True)

    @staticmethod
    def apply_if_needed(dispatcher: Dispatcher):
        if TELEGRAM_SETTINGS.SERVICE_GROUP_ID is not None:
            dispatcher.error.outer_middleware(ErrorsMiddleware())
            logger.info(
                f"error middleware: ✅ {TELEGRAM_SETTINGS.model_dump_json(indent=2, include={'SERVICE_GROUP_ID'})}")
        else:
            logger.info(f"error middleware: 💤")
