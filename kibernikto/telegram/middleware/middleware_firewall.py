import asyncio
import logging
from typing import Dict, Any, Callable, Awaitable

from aiogram import BaseMiddleware, Dispatcher
from aiogram import enums, Bot, Router
from aiogram.types import Message, TelegramObject

from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.utils.permissions import is_from_admin, admin_or_public
from kibernikto.telegram.utils.conversation import reply
from kibernikto.telegram.utils.permissions import group_allowed

from .utils import get_event_message


class FirewallMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:

        message: Message = get_event_message(event)
        if not message:
            logging.warning(f"No message found in event: {event}")
            return None

        if message.chat.type == enums.ChatType.PRIVATE:
            if admin_or_public(message):
                return await handler(event, data)
            else:
                logging.warning(f"Access denied for {message.from_user.username}")
                await reply(message, "🔑 Access is denied!")
                return None
        else:
            if group_allowed(message):
                logging.debug(f"Group Access granted for {message.from_user.username}")
                return await handler(event, data)
            else:
                logging.warning(f"Group Access denied for {message.from_user.username} in {message.chat.title}")
                return None

    @staticmethod
    def apply_if_needed(dispatcher: Dispatcher):
        middleware = FirewallMiddleware()
        dispatcher.message.outer_middleware(middleware)
        dispatcher.edited_message.outer_middleware(middleware)
        logging.info(
            f"auth middleware: ✅:\n{TELEGRAM_SETTINGS.model_dump_json(indent=2, include={'PUBLIC', 'MASTER_ID', 'MASTER_IDS', 'FRIEND_GROUP_IDS'})}")
