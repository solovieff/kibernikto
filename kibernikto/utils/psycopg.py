import logging
import numbers
from contextlib import asynccontextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, AsyncConnectionPool
from pydantic import PostgresDsn
from pydantic_settings import BaseSettings


class DBSettings(BaseSettings):
    DB_PG_URL: PostgresDsn | None = None
    PG_MIN_CONN: int = 1
    PG_MAX_CONN: int = 2
    KNKT_APP_NAME: str = "Kibernikto"


db_settings = DBSettings()


class KiberniktoPgConnection(psycopg.Connection):
    pass


class ExtendedAsyncPgConnection(psycopg.AsyncConnection):
    """
    compatibility with asyncpg and some helpful methods
    """

    async def fetch(self, query):
        res_cur = await self.execute(query)
        return await res_cur.fetchall()

    async def fetchrow(self, query):
        res_cur = await self.execute(query)
        return await res_cur.fetchall()


# for backwards compatibility
def get_connection_pool(db_url, db_label, min_conn=db_settings.PG_MIN_CONN,
                        max_conn=db_settings.PG_MAX_CONN):
    return create_sync_pool(db_url=db_url, db_label=db_label, min_conn=min_conn, max_conn=max_conn)


# for backwards compatibility
async def async_get_connection_pool(db_url, db_label, pool=None,
                                    min_conn=db_settings.PG_MIN_CONN, max_conn=db_settings.PG_MAX_CONN):
    return await create_async_pool(db_url=db_url, db_label=db_label, min_conn=min_conn, max_conn=max_conn)


def create_sync_pool(db_url, db_label="Psycopg conn", min_conn=db_settings.PG_MIN_CONN,
                     max_conn=db_settings.PG_MAX_CONN,
                     open=True):
    """

    Parameters
    ----------
    db_url:str
    db_label:str
    min_conn:int
    max_conn:int
    open:str if to open MIN conn immediately

    Returns
    -------
    psycopg_pool.ConnectionPool
    """
    try:
        pool = ConnectionPool(db_url, min_size=min_conn, max_size=max_conn, open=open, name=db_label,
                              configure=_apply_adapter, connection_class=KiberniktoPgConnection)
        _pool_test(pool, db_label)
    except Exception as e:
        logging.error(f'An error occurred while initializing {db_label}!')
        raise e
    return pool


async def create_async_pool(db_url, db_label="Psycopg conn", min_conn=db_settings.PG_MIN_CONN,
                            max_conn=db_settings.PG_MAX_CONN,
                            open=True):
    """

    Parameters
    ----------
    db_url:str
    db_label:str
    min_conn:int
    max_conn:int
    open:str if to open MIN conn immediately

    Returns
    -------
    psycopg_pool.ConnectionPool
    """
    try:
        pool = AsyncConnectionPool(db_url, min_size=min_conn,
                                   max_size=max_conn,
                                   open=open,
                                   name=db_label,
                                   check=AsyncConnectionPool.check_connection,
                                   configure=_async_apply_adapter,
                                   connection_class=ExtendedAsyncPgConnection)
        await _async_pool_test(pool, db_label)
    except Exception as e:
        logging.error(f'An error occurred while initializing {db_label}!')
        raise e
    return pool


@asynccontextmanager
async def async_get_single_connection(url):
    r"""Get single async connection.

    Yields
    -------
    asyncpg.connection.Connection

    """
    async with await ExtendedAsyncPgConnection.connect(url, row_factory=dict_row) as conn:
        yield conn


async def _async_apply_adapter(async_connection):
    # print('applying adapters to ' + str(connection) + '...')
    pass

def _pool_test(pool, db_label):
    r"""Check if connection pool is alive

    Parameters
    ----------
    pool : psycopg.ConnectionPool
        Connection pool.
    db_label : str
        DB label.

    Returns
    -------
    None

    """
    with pool.connection() as conn:
        server_time = conn.execute("SELECT now()").fetchone()[0]
        logging.info(f'{db_label} ({conn.info.dsn}) is alive! Server time: {server_time}')


def enrich_url(url, app_name, param_name="application_name"):
    """
    Adds additional values to postgres url
    Parameters
    ----------
    url
    app_name

    Returns
    -------

    """
    param_prefix = "&" if "?" in url else "?"
    return url + param_prefix + f"{param_name}={app_name}"


async def _async_pool_test(pool, db_label):
    r"""Check if connection pool is alive

    Parameters
    ----------
    pool : psycopg.ConnectionPool
        Connection pool.
    db_label : str
        DB label.

    Returns
    -------
    None

    """
    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT now()")
        server_time = await cursor.fetchone()
        logging.info(f'{db_label} ({conn.info.dsn}) is alive! Server time: {server_time[0]}')
