import logging

import logfire
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='APP_')
    INSTANCE_NAME: str = 'kibernikto-app'
    URL: str = 'https://none.com'
    TAG_NAME: str = 'kibernikto'


APP_SETTINGS = AppSettings()


def print_banner():
    logger = logging.getLogger('kibernikto')
    logger.info(APP_SETTINGS.model_dump_json(indent=2))


def configure_logger():
    formatter = logging.Formatter(
        fmt='%(levelname)-8s %(asctime)s %(name)s:%(filename)s:%(lineno)d %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S'
    )
    logfire.configure(service_name=APP_SETTINGS.INSTANCE_NAME, send_to_logfire='if-token-present')
    logfire.instrument_pydantic_ai()

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

    logger = logging.getLogger('pydantic_ai')
    logger.setLevel(logging.INFO)
