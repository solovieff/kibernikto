"""SqlHistoryStorage — per-message HistoryStorage via SQLAlchemy async (PG or SQLite).

One ``ModelMessage`` per row in ``chat_messages`` — no giant JSON blobs, no
in-memory cache, no whole-chat reads on every turn. ``get_conversation`` reads
only the tail rows needed for the window; ``add_messages`` appends new rows.
"""

import logging
from typing import List

from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessage
from sqlalchemy import func, select

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.storage.base import _sanitize, _window
from kibernikto.storage.config import STORAGE_SETTINGS
from kibernikto.storage.sql.engine import get_session
from kibernikto.storage.sql.models import ChatMessageRow

logger = logging.getLogger(__name__)

# Single-message adapter — the payload column stores one serialized ModelMessage.
_message_adapter: TypeAdapter = TypeAdapter(ModelMessage)

# Slack multiplier moved to STORAGE_SETTINGS.HISTORY_WINDOW_SLACK.


class SqlHistoryStorage:  # satisfies HistoryStorage (structural)
    """Per-message history storage — one row per ``ModelMessage``."""

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

    async def _read_tail(self, chat_id: int, limit: int) -> List[ModelMessage]:
        """Read the last ``limit`` messages for *chat_id*, oldest-first."""
        async with await get_session() as session:
            stmt = (
                select(ChatMessageRow.payload)
                .where(
                    ChatMessageRow.chat_id == chat_id,
                    ChatMessageRow.name == self._name,
                )
                .order_by(ChatMessageRow.seq.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
        messages: List[ModelMessage] = []
        for raw in reversed(rows):
            try:
                messages.append(_message_adapter.validate_python(raw))
            except Exception as exc:
                logger.warning("Skipping unparseable message for chat %s: %s", chat_id, exc)
        return messages

    async def _next_seq(self, session, chat_id: int) -> int:
        stmt = select(func.coalesce(func.max(ChatMessageRow.seq), -1)).where(
            ChatMessageRow.chat_id == chat_id,
            ChatMessageRow.name == self._name,
        )
        return (await session.execute(stmt)).scalar_one() + 1

    # ── HistoryStorage ─────────────────────────────────────────────────────

    async def get_conversation(self, chat_id: int) -> List[ModelMessage]:
        # Fetch the tail with slack so _window can align to a request boundary.
        tail = await self._read_tail(chat_id, self._history_size * STORAGE_SETTINGS.HISTORY_WINDOW_SLACK)
        return _window(tail, self._history_size)

    async def get_full_conversation(self, chat_id: int, limit: int = 5000) -> List[ModelMessage]:
        return await self._read_tail(chat_id, limit)

    async def add_messages(self, chat_id: int, messages: List[ModelMessage]) -> None:
        if not messages:
            return
        clean = _sanitize(messages, keep_thinking=self._keep_thinking)
        async with await get_session() as session:
            seq = await self._next_seq(session, chat_id)
            for msg in clean:
                session.add(ChatMessageRow(
                    chat_id=chat_id,
                    name=self._name,
                    seq=seq,
                    kind=msg.kind,
                    payload=_message_adapter.dump_python(msg, mode="json"),
                ))
                seq += 1
            await session.commit()
