from ._connectors import AsyncKiberniktoPgConnector
from kibernikto.utils.psycopg import db_settings

__DB_LABEL = 'Kibernikto Postgres'

async_connector = AsyncKiberniktoPgConnector(url=db_settings.DB_PG_URL.unicode_string(),
                                             key="ASYNC_KIBERNIKTO_PSYCOPG_DB",
                                             title=__DB_LABEL)


async def init_db():
    global async_connector
    await async_connector.init()
