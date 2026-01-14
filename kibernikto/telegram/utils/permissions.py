from aiogram import types
from pydantic_settings import BaseSettings

from telegram.config import TELEGRAM_SETTINGS


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
