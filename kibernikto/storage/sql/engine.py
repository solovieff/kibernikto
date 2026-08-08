"""SQLAlchemy async engine + sessionmaker — resolves DSN from StorageSettings."""

import asyncio
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kibernikto.storage.config import STORAGE_SETTINGS
from kibernikto.storage.sql.models import Base

logger = logging.getLogger(__name__)

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_db_initialized = False
_init_lock: asyncio.Lock | None = None


def _dsn() -> str:
    """Resolve DSN based on DATA_BACKEND. Settings are already validated at import time."""
    s = STORAGE_SETTINGS
    if s.DATA_BACKEND == "pg":
        return s.PG_DSN
    if s.DATA_BACKEND == "sqlite":
        return f"sqlite+aiosqlite:///{s.SQLITE_PATH}"
    raise RuntimeError(f"Unsupported DATA_BACKEND for SQL engine: {s.DATA_BACKEND}")


def _create_engine() -> None:
    global _engine, _sessionmaker
    url = _dsn()
    # Log DSN without credentials.
    logger.info("Creating SQLAlchemy async engine: %s", url.split("@")[-1] if "@" in url else url)
    _engine = create_async_engine(
        url, echo=False,
        json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


async def ensure_db_initialized() -> None:
    """Create tables once per process. Safe to call from any async context.

    Telegram: вызывается в ``_on_startup`` (telegram_app.py) — engine создаётся
    в том же event loop что и polling.

    Standalone (без Telegram): вызови один раз перед ``agent.run()``:

        await ensure_db_initialized()
        result = await agent.run('...', chat_id=123)
    """
    global _db_initialized, _init_lock
    if _db_initialized:
        return
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    async with _init_lock:
        if _db_initialized:  # double-check after acquiring the lock
            return
        if _engine is None:
            _create_engine()
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _db_initialized = True
        logger.info("Database tables ensured (create_all).")


async def get_session() -> AsyncSession:
    """Return an async session. Engine must be initialized via ensure_db_initialized() first."""
    if _sessionmaker is None:
        raise RuntimeError("DB not initialized — call ensure_db_initialized() first")
    return _sessionmaker()


async def shutdown_db() -> None:
    """Dispose the engine pool (call on app shutdown)."""
    global _engine, _sessionmaker, _db_initialized
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
        _db_initialized = False
        logger.info("SQL engine disposed.")
