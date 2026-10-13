"""Lazy asyncpg pool for the harness ``PostgresMemoryStore`` — created on first use inside the running loop."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from sqlalchemy.engine import make_url


def asyncpg_dsn(dsn: str) -> str:
    """Strip the SQLAlchemy driver suffix: ``postgresql+asyncpg://`` → ``postgresql://``."""
    return make_url(dsn).set(drivername="postgresql").render_as_string(hide_password=False)


class LazyAsyncpgPool:  # satisfies pydantic_ai_harness.memory.PostgresPool (structural)
    """Pool opened on the first ``acquire`` so import/build never touches the network."""

    def __init__(self, dsn: str) -> None:
        self._dsn = asyncpg_dsn(dsn)
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def _get(self) -> asyncpg.Pool:
        async with self._lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(self._dsn)
            return self._pool

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        pool = await self._get()
        async with pool.acquire() as connection:
            yield connection

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
