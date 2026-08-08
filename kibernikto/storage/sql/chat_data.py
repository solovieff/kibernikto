"""SqlChatDataStorage — ChatDataStore backed by SQLAlchemy async."""

import logging

from kibernikto.storage.models import ConversationInfo
from kibernikto.storage.sql.engine import ensure_db_initialized, get_session
from kibernikto.storage.sql.models import ChatDataRow

logger = logging.getLogger(__name__)


class SqlChatDataStorage:  # satisfies ChatDataStore (structural)
    """Per-chat data via SQLAlchemy — same interface as file-based ChatDataStorage."""

    async def load(self, chat_id: int) -> ConversationInfo:
        await ensure_db_initialized()
        async with await get_session() as session:
            row = await session.get(ChatDataRow, chat_id)
            if row is not None and row.data:
                try:
                    return ConversationInfo.model_validate(row.data)
                except Exception as exc:
                    logger.warning("Failed to parse chat data for %s: %s", chat_id, exc)
        info = ConversationInfo(tg_id=chat_id)
        await self.save(chat_id, info)
        return info

    async def save(self, chat_id: int, info: ConversationInfo) -> None:
        await ensure_db_initialized()
        data = info.model_dump(mode="json")
        async with await get_session() as session:
            row = await session.get(ChatDataRow, chat_id)
            if row is None:
                row = ChatDataRow(chat_id=chat_id, data=data)
                session.add(row)
            else:
                row.data = data
            await session.commit()
