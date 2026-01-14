import asyncio
import logging
from typing import Dict, Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram import enums, Bot, Router
from aiogram.types import Message

from kibernikto.telegram.utils.permissions import is_from_admin, admin_or_public
from kibernikto.telegram.utils.conversation import reply
from telegram.config import TELEGRAM_SETTINGS
from telegram.utils.permissions import group_allowed


class AuthMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        pass

    async def __call__(
            self,
            handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
            event: Message,
            data: Dict[str, Any]
    ) -> Any:
        if not event or not event.message:
            return await handler(event, data)

        message: Message = event.message

        if message.chat.type == enums.ChatType.PRIVATE:
            auth_passed = admin_or_public(message)
        else:
            auth_passed = group_allowed(message)

        if auth_passed:
            return await handler(event, data)
        else:
            logging.warning(f"Access denied for {message.from_user.username}")
            await reply(message, "🔑 Access is denied!")
            return None


def apply_if_needed(dispatcher: Router):
    dispatcher.message.outer_middleware(AuthMiddleware())
    logging.info(
        f"auth middleware: ✅:\n{TELEGRAM_SETTINGS.model_dump_json(indent=2, include={'PUBLIC', 'MASTER_ID', 'MASTER_IDS', 'FRIEND_GROUP_IDS'})}")
