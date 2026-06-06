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


def should_react(message: Message) -> bool:
    """Decide whether this bot should respond to ``message`` in a group.

    Reacts when the message replies to the bot or mentions any of the
    configured reaction calls (including the bot's own name and @username).
    """
    from kibernikto.telegram.runner import bot_me
    from kibernikto.telegram.utils.conversation import is_reply, get_message_text

    message_text = get_message_text(message)
    if not message_text:
        return False

    calls = [*TELEGRAM_SETTINGS.REACTION_CALLS, bot_me.full_name, f"@{bot_me.username}"]
    haystack = message_text.lower()
    mentioned = any(call.lower() in haystack for call in calls)

    return is_reply(message) or mentioned

