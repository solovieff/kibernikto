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

logger = logging.getLogger(__name__)


class FirewallMiddleware(BaseMiddleware):
    """
    Middleware that controls access to the bot based on configured permissions.

    For private chats:
    - Grants access to admins (users in MASTER_IDS) or if PUBLIC mode is enabled
    - Denies access with a message if not authorized

    For group chats:
    - Grants access if the group is in FRIEND_GROUP_IDS or if FRIEND_GROUP_IDS is not set
    - Silently denies access for unauthorized groups

    The middleware applies to both regular messages and edited messages.
    """

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:

        message: Message = get_event_message(event)
        if not message:
            logger.warning(f"No message found in event: {event}")
            return None

        if message.chat.type == enums.ChatType.PRIVATE:
            if admin_or_public(message):
                logger.debug(f"Access granted for {message.from_user.username}")
                return await handler(event, data)
            else:
                logger.warning(f"Access denied for {message.from_user.username}")
                await reply(message, "🔑 Access is denied!")
                return None
        else:
            if group_allowed(message):
                logger.debug(f"Group Access granted for {message.from_user.username}")
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
            f"firewall middleware: ✅:\n{TELEGRAM_SETTINGS.model_dump_json(indent=2, include={'PUBLIC', 'MASTER_ID', 'MASTER_IDS', 'FRIEND_GROUP_IDS'})}")
