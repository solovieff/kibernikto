# Storage

Sources: `kibernikto/storage/config.py`, `kibernikto/storage/base.py`,
`kibernikto/storage/factory.py`, `kibernikto/storage/singletons.py`.

## Backend selection

| Setting | Default | Choices |
|---|---|---|
| `APP_STORAGE_DATA_BACKEND` | `file` | `file`, `pg`, `sqlite` (history and chat data) |
| `APP_STORAGE_MEDIA_BACKEND` | `file` | `file`, `s3` (binary media) |
| `APP_STORAGE_FILESTORE_LOCATION` | `~/.kibernikto` | file data, instructions and local temporary files |
| `APP_STORAGE_SQLITE_PATH` | `:memory:` | explicit file required for restart persistence |

`get_history_storage(name)` and `get_media_store(name)` cache by namespace;
`get_chat_data_storage()` shares a single chat-data backend. Import lazy proxies from
`kibernikto.storage.singletons`, or inject an explicit backend into an agent.

```python
from kibernikto.storage.factory import get_history_storage
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from pydantic_ai.models.test import TestModel

agent = KiberniktoAgent(
    model=TestModel(), name="separate", history_storage=get_history_storage("separate")
)
```

## Layout and contracts

Under the configured filestore root:

- `history/{name}/{chat_id}.json`: `FileStoreHistoryStorage` full serialized history.
- `chat_data/{chat_id}.json`: `ConversationInfo` (facts, credits, timezone, cached chat context).
- `media/{name}/{chat_id}/{file}`: binary media; `tmp/` is transient.
- S3 object keys are `media/{name}/{chat_id}/{file}`. Returned media references omit
  namespace (`{chat_id}/{file}`), so retain the originating store when reading them.

`HistoryStorage` provides async `get_conversation`, `get_full_conversation(limit=5000)`
and `add_messages`. `MediaStore` provides async `save`/`read`, plus `tmp_path` and
`cleanup_tmp`; file-only `.path()` is not a portable S3 API. `ChatDataStore` exposes
async `load`/`save`. `MemoryHistoryStorage` remains available for tests but is not an env backend.

File history has a process-local read cache and whole-file writes. It survives a
normal restart but is not safe shared cross-process coordination; save failures are
logged rather than raised. SQL stores one model message per row in `chat_messages`,
scoped by chat ID and name, and fetches the tail without that cache. Do not promise
serialized concurrent conversation turns or distributed peer recovery merely because SQL is used.

## History window and sanitization

`_window` starts near the last `HISTORY_SIZE` messages, walks backward to a request,
then forward past a leading response-only prefix if necessary. This intentional
alignment can return **more** than the requested message count. SQL fetches at most
`HISTORY_SIZE * APP_STORAGE_HISTORY_WINDOW_SLACK` tail rows before alignment.

All implementations share sanitization: request instructions and binary `FilePart`s
are stripped; reasoning is dropped by default. `KEEP_THINKING_IN_HISTORY=true`
requests retained reasoning with signatures stripped, but inspect `_sanitize` before
promising this for every shape: its replacement currently depends on a changed part
count, so a signature-only change can be lost when no parts were removed.

## SQL and resource lifecycle

`APP_STORAGE_PG_DSN` is required for `pg`; use SQLAlchemy's asyncpg URL scheme.
For file SQLite, create the parent directory yourself; engine setup doesn't create it
or expand a tilde in the configured path. `:memory:` is intentionally ephemeral.

```python
from kibernikto.storage.sql.engine import ensure_db_initialized
from kibernikto.storage.factory import shutdown_storage

async def sql_lifecycle():
    await ensure_db_initialized()  # only for configured pg/sqlite
    try:
        # Run application work on this same event loop.
        pass
    finally:
        await shutdown_storage()
```

`TelegramApp` installs SQL initialization at startup and storage shutdown hooks.
Standalone applications must own this lifecycle. `validate_storage()` currently
HEAD-checks an S3 bucket when configured; it does not connect to SQL. Schema setup
uses `create_all`, not a migration system. S3 keeps voice temporary files local and
closes its lazy async client at shutdown.

Do not mutate global settings or swap singleton backends midway through a process;
existing agents/proxies may retain resolved objects. Use isolated processes in tests.
The scheduler expert is an exception to this storage factory: it maintains separate
JSON under the user's `.kibernikto/scheduler` directory and has no execution daemon.
