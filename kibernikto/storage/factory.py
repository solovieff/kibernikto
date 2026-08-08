"""Storage factory — lazy singletons switched by StorageSettings."""

import logging
from typing import TYPE_CHECKING

from kibernikto.storage.config import STORAGE_SETTINGS

if TYPE_CHECKING:
    from kibernikto.storage.base import ChatDataStore, HistoryStorage, MediaStore

logger = logging.getLogger(__name__)

_history_storages: dict[str, "HistoryStorage"] = {}
_chat_data_storage: "ChatDataStore | None" = None
_media_stores: dict[str, "MediaStore"] = {}


def get_history_storage(name: str = "default") -> "HistoryStorage":
    """Return a ``HistoryStorage`` backend for *name*, cached per name."""
    if name in _history_storages:
        return _history_storages[name]

    if STORAGE_SETTINGS.DATA_BACKEND in ("pg", "sqlite"):
        from kibernikto.storage.sql.history import SqlHistoryStorage
        storage: HistoryStorage = SqlHistoryStorage(name=name)
    else:
        from kibernikto.storage.file.history import FileStoreHistoryStorage
        storage = FileStoreHistoryStorage(name=name)

    _history_storages[name] = storage
    logger.info("History storage backend: %s -> %s (name=%s)", STORAGE_SETTINGS.DATA_BACKEND, type(storage).__name__, name)
    return storage


def get_chat_data_storage() -> "ChatDataStore":
    """Return the chat_data backend singleton based on ``DATA_BACKEND``."""
    global _chat_data_storage
    if _chat_data_storage is not None:
        return _chat_data_storage

    if STORAGE_SETTINGS.DATA_BACKEND in ("pg", "sqlite"):
        from kibernikto.storage.sql.chat_data import SqlChatDataStorage
        _chat_data_storage = SqlChatDataStorage()
    else:
        from kibernikto.storage.file.chat_data import ChatDataStorage
        _chat_data_storage = ChatDataStorage()

    logger.info("Chat data backend: %s -> %s", STORAGE_SETTINGS.DATA_BACKEND, type(_chat_data_storage).__name__)
    return _chat_data_storage


def get_media_store(name: str = "default") -> "MediaStore":
    """Return a media backend for *name*, cached per name.

    Namespaces:
      * ``"default"`` — agent-produced media (generations, reports)
      * ``"telegram"`` — user-uploaded media from the TG preprocessor
    """
    if name in _media_stores:
        return _media_stores[name]

    if STORAGE_SETTINGS.MEDIA_BACKEND == "s3":
        from kibernikto.storage.s3.media import S3MediaStore
        store: MediaStore = S3MediaStore(name=name)
    else:
        from kibernikto.storage.file.media import MediaFileStore
        store = MediaFileStore(name=name)

    _media_stores[name] = store
    logger.info("Media backend: %s -> %s (name=%s)", STORAGE_SETTINGS.MEDIA_BACKEND, type(store).__name__, name)
    return store


async def shutdown_storage() -> None:
    """Dispose all storage resources — call on application shutdown.

    Safe to call even when nothing was initialized (no-op).
    """
    global _chat_data_storage

    if _chat_data_storage is not None or _history_storages:
        from kibernikto.storage.sql.engine import shutdown_db
        await shutdown_db()

    from kibernikto.storage.s3.media import S3MediaStore
    for store in _media_stores.values():
        if isinstance(store, S3MediaStore):
            await store.aclose()

    _history_storages.clear()
    _chat_data_storage = None
    _media_stores.clear()
    logger.info("Storage shut down.")
