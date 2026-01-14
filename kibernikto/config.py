import logging

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='APP_')
    INSTANCE_NAME: str = 'kibernikto-app'
    TAG_NAME: str = 'kibernikto'


class KiberniktoSettings(BaseSettings):
    """This is main AI params to be used by default kibernikto instance."""
    model_config = SettingsConfigDict(env_prefix='AGENT_KIBERNIKTO_')
    INSTANCE_NAME: str = 'kibernikto'
    TAG_NAME: str = 'kibernikto'
    API_KEY: str | None = None
    BASE_URL = "https://api.vsegpt.ru:7090/v1/"
    MAX_TOKENS: int = 760
    SYSTEM_PROMPT: str = 'U are kibernikto'
    FULL_MODEL_NAME = "openai/gpt-4.1"
    TEMPERATURE = 0.7
    # history size
    MAX_MESSAGES = 6


APP_SETTINGS = AppSettings()
KIBERNIKTO_SETTINGS = KiberniktoSettings()


def print_banner():
    logging.info(APP_SETTINGS.model_dump_json(indent=2))
    logging.info(KIBERNIKTO_SETTINGS.model_dump_json(indent=2))
