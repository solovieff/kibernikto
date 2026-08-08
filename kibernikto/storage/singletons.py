"""Lazy storage singletons — resolved on first access, backed by the factory.

Import the singleton objects directly:

    from kibernikto.storage.singletons import chat_data, media_store, history_storage

Each is resolved from ``kibernikto.storage.factory`` on first attribute access,
so backends are chosen by env (``APP_STORAGE_*``) without circular imports.
"""

from typing import Any

from kibernikto.storage.factory import get_chat_data_storage, get_history_storage, get_media_store

__all__ = ["chat_data", "media_store", "history_storage"]


class _LazySingleton:
    """Lazy proxy: resolves the real backend on first attribute access."""

    __slots__ = ("_factory", "_resolved", "_name")

    def __init__(self, factory, name: str) -> None:
        object.__setattr__(self, "_factory", factory)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_resolved", None)

    def _get(self) -> Any:
        resolved = object.__getattribute__(self, "_resolved")
        if resolved is None:
            factory = object.__getattribute__(self, "_factory")
            name = object.__getattribute__(self, "_name")
            resolved = factory(name) if name else factory()
            object.__setattr__(self, "_resolved", resolved)
        return resolved

    def __getattr__(self, item: str) -> Any:
        return getattr(self._get(), item)

    @property
    def __class__(self):  # noqa: D105 — makes isinstance() see through the proxy
        return self._get().__class__

    def __repr__(self) -> str:
        resolved = object.__getattribute__(self, "_resolved")
        if resolved is None:
            return "<unresolved lazy singleton>"
        return repr(resolved)


#: Default per-chat history (name=\"default\"). Other agents call
#: ``get_history_storage(name)`` directly for their own namespace.
history_storage = _LazySingleton(get_history_storage, "default")

#: Shared per-chat data (credits, private_info) — one bucket across agents.
chat_data = _LazySingleton(get_chat_data_storage, "")

#: Agent-produced media (generations, reports, documents).
media_store = _LazySingleton(get_media_store, "default")

#: Telegram-uploaded media (user photos, voice, documents from TG).
tg_media_store = _LazySingleton(get_media_store, "telegram")
