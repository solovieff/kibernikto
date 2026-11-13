import json
import logging
from typing import Literal

import logfire
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.storage.config import STORAGE_SETTINGS


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='APP_')
    INSTANCE_NAME: str = 'kibernikto-app'
    URL: str = 'https://none.com'
    TAG_NAME: str = 'kibernikto'
    # stdlib: our formatted records next to Logfire span lines; logfire: one Logfire console stream for both
    LOG_CONSOLE: Literal['stdlib', 'logfire'] = 'stdlib'
    LOG_PYDANTIC_LEVEL: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] = 'INFO'
    # raw provider HTTP request/response bodies as Logfire spans (noisy, may contain user content)
    LOG_HTTP: bool = False


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


LOG_FORMAT = '%(levelname)-8s %(asctime)s %(name)s:%(filename)s:%(lineno)d %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d:%H:%M:%S'
LOGGER_LEVELS = {
    'kibernikto': logging.DEBUG,
    'aiogram': logging.ERROR,
    'pydantic_ai': logging.getLevelNamesMapping()[APP_SETTINGS.LOG_PYDANTIC_LEVEL],
}


def configure_logger() -> None:
    """Stdlib records + Logfire spans/export. ``APP_LOG_CONSOLE`` picks who prints: our handler or Logfire's console.

    Root stays at WARN, so third-party warnings and errors reach every sink; project loggers are more verbose.
    Logfire ignores formatters, hence the separate stdlib console handler. Safe to call more than once.
    """
    logfire.configure(service_name=APP_SETTINGS.INSTANCE_NAME, send_to_logfire='if-token-present')
    logfire.instrument_pydantic_ai()
    if APP_SETTINGS.LOG_HTTP:
        logfire.instrument_httpx(capture_all=True)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    if APP_SETTINGS.LOG_CONSOLE == 'logfire':
        # Logfire prints records and spans in one timeline; stdlib stream is only the suppressed-instrumentation fallback.
        logfire_handler = logfire.LogfireLoggingHandler(fallback=console_handler)
        handlers = [logfire_handler]
    else:
        # console_log=False: Logfire's console already shows spans; records are printed once, by our handler.
        # NullHandler fallback: records under suppressed instrumentation are already printed by our handler.
        logfire_handler = logfire.LogfireLoggingHandler(
            fallback=logging.NullHandler(),
            logfire_instance=logfire.with_settings(console_log=False),
        )
        handlers = [console_handler, logfire_handler]

    logging.basicConfig(level=logging.WARN, handlers=handlers, force=True)
    for name, level in LOGGER_LEVELS.items():
        logging.getLogger(name).setLevel(level)
