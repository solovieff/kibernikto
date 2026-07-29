import logging
from pathlib import Path
from typing import List

from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessage

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.config import APP_SETTINGS
from kibernikto.storage.base import MemoryHistoryStorage

logger = logging.getLogger(__name__)

_model_message_adapter: TypeAdapter = TypeAdapter(list[ModelMessage])


class FileStoreHistoryStorage(MemoryHistoryStorage):
    """In-memory + JSON persistence under ``{FILESTORE_LOCATION}/history/{name}/{chat_id}.json``."""

    _FILESTORE_ROOT = Path(APP_SETTINGS.FILESTORE_LOCATION).expanduser()

    def __init__(self, *, name: str, history_size: int = AGENT_KIBERNIKTO_SETTINGS.HISTORY_SIZE) -> None:
        super().__init__(history_size)
        self._name = name

    # ── file helpers ───────────────────────────────────────────────────────

    def _dir(self) -> Path:
        p = self._FILESTORE_ROOT / "history" / self._name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _path(self, chat_id: int) -> Path:
        return self._dir() / f"{chat_id}.json"

    def _save(self, chat_id: int) -> None:
        messages = self._storage.get(chat_id)
        if messages is None:
            return
        try:
            data = _model_message_adapter.dump_json(messages)
            self._path(chat_id).write_text(data.decode("utf-8"), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save history for chat %s: %s", chat_id, exc)

    def _load(self, chat_id: int) -> None:
        if chat_id in self._storage:
            return
        path = self._path(chat_id)
        if not path.exists():
            self._storage[chat_id] = []
            return
        try:
            messages = _model_message_adapter.validate_json(path.read_text(encoding="utf-8"))
            self._storage[chat_id] = messages
        except Exception as exc:
            logger.warning("Failed to load history for chat %s: %s", chat_id, exc)
            self._storage[chat_id] = []

    # ── overrides ──────────────────────────────────────────────────────────

    def get_conversation(self, chat_id: int) -> List[ModelMessage]:
        self._load(chat_id)
        return super().get_conversation(chat_id)

    def add_messages(self, chat_id: int, messages: List[ModelMessage]) -> None:
        if chat_id not in self._storage:
            self._load(chat_id)
        super().add_messages(chat_id, messages)
        self._save(chat_id)