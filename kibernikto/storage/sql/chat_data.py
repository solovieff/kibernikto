"""SqlChatDataStorage — ChatDataStore backed by SQLAlchemy async."""

import logging

from kibernikto.storage.models import ConversationInfo
from kibernikto.storage.sql.engine import get_session
from kibernikto.storage.sql.models import ChatDataRow

logger = logging.getLogger(__name__)


class SqlChatDataStorage:  # satisfies ChatDataStore (structural)
    """Per-conversation data via SQLAlchemy — same interface as file-based ChatDataStorage."""

    async def load(self, conversation_id: str) -> ConversationInfo:
        cid = str(conversation_id)
        async with await get_session() as session:
            row = await session.get(ChatDataRow, cid)
            if row is not None and row.data:
                try:
                    return ConversationInfo.model_validate(row.data)
                except Exception as exc:
                    logger.warning("Failed to parse chat data for %s: %s", cid, exc)
        info = ConversationInfo()
        await self.save(cid, info)
        return info

    async def save(self, conversation_id: str, info: ConversationInfo) -> None:
        cid = str(conversation_id)
        data = info.model_dump(mode="json")
        async with await get_session() as session:
            row = await session.get(ChatDataRow, cid)
            if row is None:
                row = ChatDataRow(conversation_id=cid, data=data)
                session.add(row)
            else:
                row.data = data
            await session.commit()
