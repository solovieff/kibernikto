import logging
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='TG_')
    BOT_KEY: str | None = None
    MASTER_ID: int = Field(default=199740245, description="Main admin tg id")
    MASTER_IDS: List[int] = [199740245]
    PUBLIC: bool = Field(default=True, description="If everyone can talk privately")
    FRIEND_GROUP_IDS: List[int] | None = Field(default=None, description="If present only these groups are allowed")
    PRIVILEGED_USERS: List[int] | None = Field(default=None, description="Special user ids")
    SERVICE_GROUP_ID: int | None = Field(default=None, description="Service group id")
    CHUNK_SENTENCES: int = Field(default=1024, description="Max sentences per message")
    REACTION_CALLS: List[str] = Field(default=['honda', 'киберникто'],
                                      description="In group chats, kibernikto will react to this phrases and his bot name")
    SAY_HI: bool = Field(default=False, description="If to send system telegram message on start")
    STICKER_IDS: List[str] = ["CAACAgIAAxkBAAEQPFJpZpza5ISCVgABh0uT6CYX9HgwevYAAu5KAAK-HmBK9OlWUNgz8-w4BA"]
    STICKER_PROBABILITY: float = Field(default=0.13, description="How often to send stickers")
    MAX_MESSAGE_LENGTH: int = Field(default=4096, description="Do not change, telegram default")
    MAX_CAPTION_LENGTH: int = Field(default=1023, description="Do not change, telegram default")


TELEGRAM_SETTINGS = TelegramSettings()


def print_banner():
    logger.info(f"TELEGRAM_SETTINGS: {TELEGRAM_SETTINGS.model_dump_json(indent=2)}")
