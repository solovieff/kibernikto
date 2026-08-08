import json
import logging

import logfire
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.storage.config import STORAGE_SETTINGS


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='APP_')
    INSTANCE_NAME: str = 'kibernikto-app'
    URL: str = 'https://none.com'
    TAG_NAME: str = 'kibernikto'


APP_SETTINGS = AppSettings()


def print_banner():
    logger = logging.getLogger('kibernikto')
    logger.info(APP_SETTINGS.model_dump_json(indent=2))
    logger.info(json.dumps(_storage_dump(), indent=2, ensure_ascii=False))


def _mask_dsn(dsn: str) -> str:
    """Show scheme, host and db — mask only credentials."""
    if '@' not in dsn:
        return dsn
    creds, rest = dsn.rsplit('@', 1)
    scheme = creds.split('://')[0] if '://' in creds else ''
    prefix = f'{scheme}://' if scheme else ''
    return f'{prefix}***:***@{rest}'


def _storage_dump() -> dict:
    """Dump storage settings — only fields relevant to the active backends, secrets masked."""
    s = STORAGE_SETTINGS
    dump: dict = {
        'DATA_BACKEND': s.DATA_BACKEND,
        'MEDIA_BACKEND': s.MEDIA_BACKEND,
    }
    if s.DATA_BACKEND == 'pg':
        dump['PG_DSN'] = _mask_dsn(s.PG_DSN) if s.PG_DSN else None
    elif s.DATA_BACKEND == 'sqlite':
        dump['SQLITE_PATH'] = s.SQLITE_PATH
    else:
        dump['FILESTORE_LOCATION'] = s.FILESTORE_LOCATION
    if s.MEDIA_BACKEND == 's3':
        dump['S3_ENDPOINT'] = s.S3_ENDPOINT
        dump['S3_BUCKET'] = s.S3_BUCKET
        dump['S3_REGION'] = s.S3_REGION
        dump['S3_ACCESS_KEY'] = '***' if s.S3_ACCESS_KEY else None
        dump['S3_SECRET_KEY'] = '***' if s.S3_SECRET_KEY else None
    return dump


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
