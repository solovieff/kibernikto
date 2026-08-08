# Backward-compat shim — prefer ``from kibernikto.storage.base import ...``.

from kibernikto.storage.base import HistoryStorage, MemoryHistoryStorage, _sanitize, _window

# Lazily resolved via factory: picks FileStoreHistoryStorage / SqlHistoryStorage by env.
_history_storage = None


def __getattr__(name: str):
    if name == "history_storage":
        global _history_storage
        if _history_storage is None:
            from kibernikto.storage.factory import get_history_storage
            _history_storage = get_history_storage("default")
        return _history_storage
    raise AttributeError(name)


__all__ = ["HistoryStorage", "MemoryHistoryStorage", "_sanitize", "_window", "history_storage"]
