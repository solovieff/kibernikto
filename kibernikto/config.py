from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class KiberniktoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='KIBERNIKTO_')
    INSTANCE_NAME = 'kibernikto'
    TAG_NAME = 'kibernikto'


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='TG_')
    BOT_KEY: str | None = None
    MASTER_ID: int = 199740245
    MASTER_IDS: List[int] = [199740245]
    FRIEND_GROUP_IDS: List[int] | None = None
    PRIVILEGED_USERS: List[int] | None = None
    MAX_MESSAGE_LENGTH: int = 4096
    TG_CHUNK_SENTENCES: int = 7
    REACTION_CALLS: List[str] = ['honda', 'киберникто']
    SAY_HI: bool = False
    STICKER_LIST: List[str] = ["CAACAgIAAxkBAAEQPFJpZpza5ISCVgABh0uT6CYX9HgwevYAAu5KAAK-HmBK9OlWUNgz8-w4BA"]


KIBERNIKTO_SETTINGS = KiberniktoSettings()
TELEGRAM_SETTINGS = TelegramSettings()
