"""SqlChatDataStorage — ChatDataStorage backed by SQLAlchemy async."""

import logging
from typing import Optional

from kibernikto.storage.file.models import ConversationInfo
from kibernikto.storage.sql.engine import get_session, init_db
from kibernikto.storage.sql.models import ChatDataRow

logger = logging.getLogger(__name__)


class SqlChatDataStorage:
    """Per-chat data via SQLAlchemy — same interface as file-based ChatDataStorage."""

    async def _ensure_table(self) -> None:
        await init_db()

    def _to_dict(self, info: ConversationInfo) -> dict:
        return info.model_dump(mode="json")

    def _from_dict(self, data: dict) -> ConversationInfo:
        return ConversationInfo.model_validate(data)

    async def load(self, chat_id: int) -> ConversationInfo:
        await self._ensure_table()
        async with await get_session() as session:
            row = await session.get(ChatDataRow, chat_id)
            if row is not None and row.data:
                try:
                    return self._from_dict(row.data)
                except Exception as exc:
                    logger.warning("Failed to parse chat data for %s: %s", chat_id, exc)
        info = ConversationInfo(tg_id=chat_id)
        await self.save(chat_id, info)
        return info

    async def save(self, chat_id: int, info: ConversationInfo) -> None:
        await self._ensure_table()
        data = self._to_dict(info)
        async with await get_session() as session:
            row = await session.get(ChatDataRow, chat_id)
            if row is None:
                row = ChatDataRow(chat_id=chat_id, data=data)
                session.add(row)
            else:
                row.data = data
            await session.commit()
