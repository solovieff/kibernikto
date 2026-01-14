import asyncio
import logging
from typing import Dict, Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram import enums, Bot, Router
from aiogram.types import Message

from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.utils.permissions import is_from_admin


class MessagesMiddleware(BaseMiddleware):
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
        if not event or not event.message or event.message.chat.type != enums.ChatType.PRIVATE:
            return await handler(event, data)
        asyncio.create_task(self.forward_message_service_group(event.message))
        return await handler(event, data)

    async def forward_message_service_group(self, message: Message) -> None:
        try:
            if not is_from_admin(message):
                await message.forward(chat_id=self.service_group_id)
        except Exception as e:
            logging.exception(f"failed to send service message {e}", exc_info=True)


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
        if not event:
            return await handler(event, data)

        if not event.update or not event.update.message:
            return await handler(event, data)

        user_message = event.update.message

        service_message = f"🔥🔥🔥 {user_message.from_user.username} {user_message.content_type}: {user_message.md_text} {event.exception}"
        asyncio.create_task(self.send_message_to_service_group(bot=event.update.bot, service_message=service_message))

        return await handler(event, data)

    async def send_message_to_service_group(self, bot: Bot, service_message: str) -> None:
        try:
            await bot.send_message(self.service_group_id, service_message)
        except Exception as e:
            logging.exception(f"failed to send service message {e}", exc_info=True)


def apply_if_needed(dispatcher: Router):
    if TELEGRAM_SETTINGS.SERVICE_GROUP_ID is not None:
        dispatcher.message.outer_middleware(MessagesMiddleware())
        dispatcher.error.outer_middleware(ErrorsMiddleware())
        logging.info(f"messages and error middlewares: ✅. Service group id: {TELEGRAM_SETTINGS.SERVICE_GROUP_ID}")
    else:
        logging.info(f"messages and error middlewares: 💤")
