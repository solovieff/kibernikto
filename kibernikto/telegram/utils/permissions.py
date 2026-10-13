from aiogram import types
from aiogram.types import Message


from kibernikto.telegram.config import TELEGRAM_SETTINGS


def is_admin_id(user_id: int) -> bool:
    return user_id == TELEGRAM_SETTINGS.MASTER_ID or user_id in TELEGRAM_SETTINGS.MASTER_IDS


def is_from_admin(message: types.Message):
    return is_admin_id(message.from_user.id)


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
    from kibernikto.ai.agent.telegram.identity import BotIdentity, get_bot_identity
    from kibernikto.telegram.utils.conversation import is_reply, get_message_text

    if is_reply(message):
        return True

    message_text = get_message_text(message)
    if not message_text:
        return False

    me = get_bot_identity() or BotIdentity()
    own = [me.full_name, f"@{me.username}" if me.username else None]
    calls = [*TELEGRAM_SETTINGS.REACTION_CALLS, *filter(None, own)]
    haystack = message_text.lower()
    return any(call.lower() in haystack for call in calls)

