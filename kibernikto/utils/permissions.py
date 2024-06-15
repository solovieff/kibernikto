from aiogram import types
from pydantic_settings import BaseSettings


class PermissionsSettings(BaseSettings):
    TG_PUBLIC: bool = False
    TG_MASTER_ID: int
    TG_MASTER_IDS: list = []


PERMISSIONS_SETTINGS = PermissionsSettings()


def is_from_admin(message: types.Message):
    if message.from_user.id == PERMISSIONS_SETTINGS.TG_MASTER_ID:
        return True

    if message.from_user.id in PERMISSIONS_SETTINGS.TG_MASTER_IDS:
        return True

    return False


def admin_or_public(message: types.Message):
    return is_from_admin(message) or is_public()


def is_public() -> bool:
    return PERMISSIONS_SETTINGS.TG_PUBLIC
