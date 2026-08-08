"""Storage factory — lazy singletons switched by StorageSettings."""

import logging

from kibernikto.storage.config import STORAGE_SETTINGS

logger = logging.getLogger(__name__)

_history_storage = None
_chat_data_storage = None
_media_store = None


def get_history_storage(name: str):
    """Return a ``HistoryStorage`` backend based on ``DATA_BACKEND``."""
    global _history_storage
    if _history_storage is not None:
        return _history_storage

    if STORAGE_SETTINGS.DATA_BACKEND in ("pg", "sqlite"):
        from kibernikto.storage.sql.history import SqlHistoryStorage
        _history_storage = SqlHistoryStorage(name=name)
    else:
        from kibernikto.storage.file.history import FileStoreHistoryStorage
        _history_storage = FileStoreHistoryStorage(name=name)

    logger.info("History storage backend: %s -> %s", STORAGE_SETTINGS.DATA_BACKEND, type(_history_storage).__name__)
    return _history_storage


def get_chat_data_storage():
    """Return a chat_data backend based on ``DATA_BACKEND``."""
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


def get_media_store():
    """Return a media backend based on ``MEDIA_BACKEND``."""
    global _media_store
    if _media_store is not None:
        return _media_store

    if STORAGE_SETTINGS.MEDIA_BACKEND == "s3":
        from kibernikto.storage.s3.media import S3MediaStore
        _media_store = S3MediaStore()
    else:
        from kibernikto.storage.file.media import MediaFileStore
        _media_store = MediaFileStore()

    logger.info("Media backend: %s -> %s", STORAGE_SETTINGS.MEDIA_BACKEND, type(_media_store).__name__)
    return _media_store