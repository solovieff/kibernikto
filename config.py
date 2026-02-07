import logging

import logfire
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
    BASE_URL: str = "https://api.vsegpt.ru:7090/v1/"
    MAX_TOKENS: int = 760
    SYSTEM_PROMPT: str = 'U are kibernikto'
    FULL_MODEL_NAME: str = "openai/gpt-4.1"
    TEMPERATURE: float = 0.7
    # history size
    MAX_MESSAGES: int = 6


APP_SETTINGS = AppSettings()
KIBERNIKTO_SETTINGS = KiberniktoSettings()


def print_banner():
    logger = logging.getLogger('kibernikto')
    logger.info(APP_SETTINGS.model_dump_json(indent=2))
    logger.info(KIBERNIKTO_SETTINGS.model_dump_json(indent=2))


def configure_logger():
    formatter = logging.Formatter(
        fmt='%(levelname)-8s %(asctime)s %(name)s:%(filename)s:%(lineno)d %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S'
    )
    logfire.configure(service_name=APP_SETTINGS.INSTANCE_NAME, send_to_logfire='if-token-present')

    logfire_handler = logfire.LogfireLoggingHandler()

    # FIXME: does not work
    logfire_handler.setFormatter(formatter)

    # XXX: this will push all logging to logfire
    logging.basicConfig(
        format=formatter._fmt,
        datefmt=formatter.datefmt,
        level=logging.WARN,
        handlers=[logfire_handler])

    logger = logging.getLogger('kibernikto')
    logger.setLevel(logging.DEBUG)

    logger = logging.getLogger('aiogram')
    logger.setLevel(logging.INFO)
