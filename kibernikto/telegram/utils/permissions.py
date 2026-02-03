from typing import List

from aiogram import types
from aiogram.types import Message

from kibernikto.telegram.config import TELEGRAM_SETTINGS


def is_from_admin(message: types.Message):
    if message.from_user.id == TELEGRAM_SETTINGS.MASTER_ID:
        return True

    if message.from_user.id in TELEGRAM_SETTINGS.MASTER_IDS:
        return True

    return False


def admin_or_public(message: types.Message):
    return is_from_admin(message) or is_public()


def is_public() -> bool:
    return TELEGRAM_SETTINGS.PUBLIC


def group_allowed(message: types.Message):
    if not TELEGRAM_SETTINGS.FRIEND_GROUP_IDS:
        return True
    else:
        return message.chat.id in TELEGRAM_SETTINGS.FRIEND_GROUP_IDS


def should_react(message: Message):
    """
    outer scope method to be used to understand if this instance should process the message
    :param message_text:
    :return:
    """
    from kibernikto.telegram.runner import bot_me
    from telegram.utils.conversation import is_reply, get_message_text
    calls: List[str] = [] + TELEGRAM_SETTINGS.REACTION_CALLS
    calls.append(bot_me.full_name)
    calls.append(f"@{bot_me.username}")
    message_text = get_message_text(message)
    if not message_text:
        return False

    call_to_react = any(word.lower() in message_text.lower() for word in calls)

    return is_reply(message) or call_to_react
