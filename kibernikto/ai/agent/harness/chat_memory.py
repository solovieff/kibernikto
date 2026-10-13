"""Per-chat memory: stock harness ``Memory`` notebook + ``ConversationSearch`` over our own history storage."""

from __future__ import annotations

from dataclasses import dataclass, replace

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage
from pydantic_ai_harness.conversation_search import ConversationSearch
from pydantic_ai_harness.memory import Memory, MemoryStore
from pydantic_ai_harness.step_persistence import RunRecord

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.factory import get_history_storage, get_memory_store

FULL_HISTORY_LIMIT = 5000
NO_CHAT_NAMESPACE = "no-chat"  # Shared notebook for runs without a Telegram chat (tests, scripts).


def _chat_id(deps: object) -> int | None:
    return deps.chat_id if isinstance(deps, TelegramDeps) else None


def chat_namespace(ctx: RunContext[TelegramDeps]) -> str:
    """Memory tenant = Telegram chat; resolved by app code, never by the model."""
    chat_id = _chat_id(ctx.deps)
    return NO_CHAT_NAMESPACE if chat_id is None else str(chat_id)


@dataclass(frozen=True)
class ChatHistorySource:  # satisfies conversation_search.HistorySource (structural)
    """One chat's full persisted history as a single searchable run; empty without a chat."""

    storage: HistoryStorage
    chat_id: int | None = None

    @property
    def run_id(self) -> str:
        return f"chat-{self.chat_id}"

    async def list_runs(self) -> list[RunRecord]:
        if self.chat_id is None:
            return []
        return [RunRecord(run_id=self.run_id, conversation_id=str(self.chat_id))]

    async def run_history(self, *, run_id: str) -> list[ModelMessage]:
        if self.chat_id is None or run_id != self.run_id:
            return []
        return await self.storage.get_full_conversation(self.chat_id, limit=FULL_HISTORY_LIMIT)


@dataclass
class ChatConversationSearch(ConversationSearch[TelegramDeps]):
    """``ConversationSearch`` bound per run to the caller's chat; the source is the isolation boundary."""

    async def for_run(self, ctx: RunContext[TelegramDeps]) -> ChatConversationSearch:
        return replace(self, source=replace(self.source, chat_id=_chat_id(ctx.deps)))


def chat_memory(name: str, *, store: MemoryStore | None = None,
                history: HistoryStorage | None = None) -> list[AbstractCapability[TelegramDeps]]:
    """Notebook (auto-injected ``MEMORY.md`` + write/read/search tools) and BM25 recall of the chat's full history."""
    return [
        Memory(store or get_memory_store(), agent_name=name, namespace=chat_namespace),
        # scope='all' is safe: the per-run source only ever enumerates the caller's own chat.
        ChatConversationSearch(ChatHistorySource(history or get_history_storage(name)), scope="all"),
    ]
