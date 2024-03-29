from contextlib import asynccontextmanager

import psycopg
from psycopg.rows import dict_row

from kibernikto.utils import text as text_utils
from kibernikto.utils.psycopg import db_settings
from kibernikto.utils.psycopg import enrich_url, create_async_pool


class AsyncKiberniktoPgConnector:
    def __init__(self, url, key, title):
        self.app_name = db_settings.KNKT_APP_NAME
        self.key = key
        self.title = title
        self._url = url
        self._initialized = False

    def _check_ready(self):
        if not self.initialized():
            raise RuntimeError(f"Connector {self.key}, {self.title} was not initialized!")

    def initialized(self):
        return self._initialized

    async def init(self):
        # pg_url = text_utils.enrich_url(self._url, self.app_name)
        pg_url = self._url
        self.__pool = await create_async_pool(db_url=pg_url, db_label=self.title)
        self._initialized = True

    @asynccontextmanager
    async def get_connection(self, row_factory=dict_row, autocommit=True):
        self._check_ready()
        async with self.__pool.connection() as conn:
            conn.row_factory = row_factory
            if autocommit:
                await conn.set_autocommit(autocommit)
            yield conn

    @asynccontextmanager
    async def get_single_connection(self, row_factory=dict_row, autocommit=True):
        pg_url = enrich_url(self._url, self.app_name + "_s")
        async with await psycopg.AsyncConnection.connect(pg_url, row_factory=row_factory,
                                                         autocommit=autocommit) as conn:
            yield conn
