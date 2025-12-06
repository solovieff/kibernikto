import logging

from aiogram.types import Message, Chat

from avatar.utils.permissions import is_admin
from kibernikto.telegram import executor_exists, get_ai_executor_full

logger = logging.getLogger("kibernikto")


async def get_ready_executor(message: Message, hide_errors: bool = True):
    """

    :param message: telegram message
    :param hide_errors: if the errors should be processed in Kibernikto superclass or sent to the top
    :return:
    """
    from kibernikto.telegram.dispatcher import TELEGRAM_SETTINGS

    chat_id = message.chat.id

    if not executor_exists(chat_id):
        chat_info: Chat = await message.bot.get_chat(chat_id)
        just_created_executor = True
    else:
        chat_info = message.chat
        just_created_executor = False
    user_ai = get_ai_executor_full(chat=chat_info, user=message.from_user,
                                   hide_errors=hide_errors)
    if just_created_executor and message.chat.id in TELEGRAM_SETTINGS.TG_PRIVILEGED_USERS:
        logger.info(f"Privileged usage {message.from_user.username} is using the bot, setting doubled params")
        user_ai.max_messages = user_ai.max_messages * 2
        user_ai.full_config.max_messages = user_ai.full_config.max_messages * 2
        user_ai.full_config.max_tokens = user_ai.full_config.max_tokens * 2
    return user_ai
