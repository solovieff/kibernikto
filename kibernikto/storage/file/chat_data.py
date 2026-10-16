import asyncio
import logging
from pathlib import Path

from kibernikto.storage.config import STORAGE_SETTINGS
from kibernikto.storage.models import ConversationInfo

logger = logging.getLogger(__name__)


class ChatDataStorage:  # satisfies ChatDataStore (structural)
    """Per-conversation JSON storage under ``{FILESTORE_LOCATION}/chat_data/{conversation_id}.json``."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(STORAGE_SETTINGS.FILESTORE_LOCATION).expanduser()

    def _dir(self) -> Path:
        p = self._root / "chat_data"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _path(self, conversation_id: str) -> Path:
        return self._dir() / f"{conversation_id}.json"

    async def load(self, conversation_id: str) -> ConversationInfo:
        """Load ConversationInfo for conversation_id, creating defaults on first use."""
        cid = str(conversation_id)
        path = self._path(cid)
        if path.exists():
            try:
                text = await asyncio.to_thread(path.read_text, "utf-8")
                return ConversationInfo.model_validate_json(text)
            except Exception as exc:
                logger.warning("Failed to load chat data for %s: %s", cid, exc)
        info = ConversationInfo()
        await self.save(cid, info)
        return info

    async def save(self, conversation_id: str, info: ConversationInfo) -> None:
        """Persist ConversationInfo to JSON."""
        path = self._path(str(conversation_id))
        await asyncio.to_thread(path.write_text, info.model_dump_json(indent=2), "utf-8")
