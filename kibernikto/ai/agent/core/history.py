# Backward-compat shim — prefer ``from kibernikto.storage.base import ...``.

from kibernikto.storage.base import HistoryStorage, MemoryHistoryStorage, _sanitize, _window

# Singleton kept here to avoid the circular chain:
#   shim → kibernikto.storage → file.* → config → agent.__init__ → kibernikto_agent → shim
history_storage = MemoryHistoryStorage()

__all__ = ["HistoryStorage", "MemoryHistoryStorage", "_sanitize", "_window", "history_storage"]
