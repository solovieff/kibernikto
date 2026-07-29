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

    def load(self, chat_id: int) -> ConversationInfo:
        """Load ConversationInfo for chat_id, creating defaults on first use."""
        path = self._path(chat_id)
        if path.exists():
            try:
                return ConversationInfo.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to load chat data for %s: %s", chat_id, exc)
        info = ConversationInfo(tg_id=chat_id)
        self.save(chat_id, info)
        return info

    def save(self, chat_id: int, info: ConversationInfo) -> None:
        """Persist ConversationInfo to JSON."""
        path = self._path(chat_id)
        path.write_text(info.model_dump_json(indent=2), encoding="utf-8")


#: Module-level singleton — user data is shared across all agents.
chat_data = ChatDataStorage()
