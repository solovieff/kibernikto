"""Notebook for delegated experts: stock harness ``Memory`` scoped to the Telegram chat, not the delegated task."""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai_harness.memory import Memory, MemoryStore

from kibernikto.storage.factory import get_memory_store

NO_CHAT_NAMESPACE = 'no-chat'  # Shared notebook for runs without a chat (tests, scripts).
EXPERT_NOTEBOOKS: set[str] = set()  # Names of experts that keep a notebook, so /reset can wipe them too.


def conversation_key(deps: object) -> str | None:
    """Chat id of this run: the parent's Telegram message survives into delegated runs."""
    message = getattr(deps, 'message', None)
    chat = getattr(message, 'chat', None)
    chat_id = getattr(chat, 'id', None)
    if chat_id is not None:
        return str(chat_id)
    user_id = getattr(deps, 'user_id', None)
    return str(user_id) if user_id is not None else None


def chat_namespace(ctx: RunContext) -> str:
    """Notebook tenant = the chat, because ``ctx.conversation_id`` of a delegate is its task id."""
    return conversation_key(ctx.deps) or (ctx.conversation_id or NO_CHAT_NAMESPACE)


def expert_memory(name: str, *, heading: str, guidance: str, store: MemoryStore | None = None) -> Memory:
    """Per-chat notebook the expert curates itself; saved notes ride in the user turn under ``heading``."""
    EXPERT_NOTEBOOKS.add(name)
    return Memory(
        store or get_memory_store(),
        agent_name=name,
        namespace=chat_namespace,
        guidance=guidance,
        heading=heading,
    )
