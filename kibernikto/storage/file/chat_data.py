import logging
from pathlib import Path

from kibernikto.config import APP_SETTINGS
from kibernikto.storage.file.models import ConversationInfo

logger = logging.getLogger(__name__)


class ChatDataStorage:
    """Per-chat JSON storage under ``{FILESTORE_LOCATION}/chat_data/{chat_id}.json``."""

    _FILESTORE_ROOT = Path(APP_SETTINGS.FILESTORE_LOCATION).expanduser()

    def _dir(self) -> Path:
        p = self._FILESTORE_ROOT / "chat_data"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _path(self, chat_id: int) -> Path:
        return self._dir() / f"{chat_id}.json"

    async def load(self, chat_id: int) -> ConversationInfo:
        """Load ConversationInfo for chat_id, creating defaults on first use."""
        import asyncio
        path = self._path(chat_id)
        if path.exists():
            try:
                text = await asyncio.to_thread(path.read_text, "utf-8")
                return ConversationInfo.model_validate_json(text)
            except Exception as exc:
                logger.warning("Failed to load chat data for %s: %s", chat_id, exc)
        info = ConversationInfo(tg_id=chat_id)
        await self.save(chat_id, info)
        return info

    async def save(self, chat_id: int, info: ConversationInfo) -> None:
        """Persist ConversationInfo to JSON."""
        import asyncio
        path = self._path(chat_id)
        await asyncio.to_thread(path.write_text, info.model_dump_json(indent=2), "utf-8")


#: Lazily resolved module-level singleton (PEP 562).
_chat_data = None


def __getattr__(name: str):
    if name == "chat_data":
        global _chat_data
        if _chat_data is None:
            from kibernikto.storage.factory import get_chat_data_storage
            _chat_data = get_chat_data_storage()
        return _chat_data
    raise AttributeError(name)
