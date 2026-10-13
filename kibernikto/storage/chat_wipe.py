"""Erase one chat's persisted conversation and the agent's notebook for it; credits (chat_data) stay."""

from typing import TYPE_CHECKING

from kibernikto.storage.base import HistoryStorage

if TYPE_CHECKING:
    from pydantic_ai_harness.memory import MemoryStore

_PAGE = 100


async def wipe_chat_memory(chat_id: int, agent_name: str, store: "MemoryStore | None" = None) -> int:
    """Delete every notebook file of ``agent_name`` in ``chat_id``; returns how many were removed."""
    if store is None:
        from kibernikto.storage.factory import get_memory_store
        store = get_memory_store()
    prefix = f"{chat_id}/{agent_name}/"  # Same scope the harness Memory builds: `{namespace}/{agent_name}`.
    removed = 0
    while paths := await store.list_paths(prefix, limit=_PAGE):
        for path in paths:
            current = await store.read(path, max_chars=1)
            await store.delete(path, expected_version=current.version if current else None)
            removed += 1
    return removed


async def wipe_chat(chat_id: int, *, history: HistoryStorage | None, agent_name: str,
                    memory: "MemoryStore | None" = None) -> int:
    """Clear the chat's history and notebook; returns the number of notebook files removed."""
    if history is not None:
        await history.replace_messages(chat_id, [])
    return await wipe_chat_memory(chat_id, agent_name, memory)
