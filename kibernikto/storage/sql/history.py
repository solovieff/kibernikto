"""SqlHistoryStorage — HistoryStorage backed by SQLAlchemy async (PG or SQLite)."""

import logging
from collections import defaultdict
from typing import Dict, List

from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessage
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.storage.base import _sanitize, _window
from kibernikto.storage.sql.engine import get_session, init_db
from kibernikto.storage.sql.models import ChatHistoryRow

logger = logging.getLogger(__name__)

_model_message_adapter: TypeAdapter = TypeAdapter(list[ModelMessage])


class SqlHistoryStorage:  # satisfies HistoryStorage (structural)
    """History storage via SQLAlchemy async — shared PG/SQLite impl.

    Keeps an in-memory cache (same ``defaultdict`` pattern as file variant)
    so repeated reads within the same process don't hit the DB every turn.
    """

    def __init__(
        self,
        *,
        name: str,
        history_size: int = AGENT_KIBERNIKTO_SETTINGS.HISTORY_SIZE,
        keep_thinking: bool = AGENT_KIBERNIKTO_SETTINGS.KEEP_THINKING_IN_HISTORY,
    ) -> None:
        self._name = name
        self._history_size = history_size
        self._keep_thinking = keep_thinking
        self._storage: Dict[int, List[ModelMessage]] = defaultdict(list)
        self._loaded: set[int] = set()  # track which chat_ids are already in cache

    async def _ensure_table(self) -> None:
        await init_db()

    async def _load(self, chat_id: int) -> None:
        if chat_id in self._loaded:
            return
        await self._ensure_table()
        async with await get_session() as session:
            row = await session.get(ChatHistoryRow, chat_id)
            if row is not None and row.messages:
                try:
                    messages = _model_message_adapter.validate_python(row.messages)
                    messages = _sanitize(messages, keep_thinking=self._keep_thinking)
                    self._storage[chat_id] = messages
                except Exception as exc:
                    logger.warning("Failed to parse history for chat %s: %s", chat_id, exc)
                    self._storage[chat_id] = []
            else:
                self._storage[chat_id] = []
        self._loaded.add(chat_id)

    async def _save(self, chat_id: int) -> None:
        messages = self._storage.get(chat_id)
        if messages is None:
            return
        await self._ensure_table()
        raw = _model_message_adapter.dump_python(
            _sanitize(messages, keep_thinking=self._keep_thinking), mode="json"
        )
        async with await get_session() as session:
            row = await session.get(ChatHistoryRow, chat_id)
            if row is None:
                row = ChatHistoryRow(chat_id=chat_id, messages=raw)
                session.add(row)
            else:
                row.messages = raw
            await session.commit()

    # ── HistoryStorage ─────────────────────────────────────────────────────

    async def get_conversation(self, chat_id: int) -> List[ModelMessage]:
        await self._load(chat_id)
        return _window(self._storage[chat_id], self._history_size)

    async def add_messages(self, chat_id: int, messages: List[ModelMessage]) -> None:
        await self._load(chat_id)
        self._storage[chat_id].extend(messages)
        self._storage[chat_id] = _sanitize(self._storage[chat_id], keep_thinking=self._keep_thinking)
        await self._save(chat_id)
