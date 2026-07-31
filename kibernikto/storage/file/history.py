import dataclasses
import logging
from pathlib import Path
from typing import List

from pydantic import TypeAdapter
from pydantic_ai.messages import FilePart, ModelMessage, ModelResponse, ThinkingPart

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.config import APP_SETTINGS
from kibernikto.storage.base import MemoryHistoryStorage

logger = logging.getLogger(__name__)

_model_message_adapter: TypeAdapter = TypeAdapter(list[ModelMessage])


def _sanitize(messages: List[ModelMessage]) -> List[ModelMessage]:
    """Drop binaries and provider signatures so history JSON stays small.

    Generated images are delivered to the user and archived in the media
    store; persisting them here as base64 would bloat the file and re-send
    the bytes to the provider on every turn. ``ThinkingPart.signature`` is a
    provider watermark that is not needed to continue the dialogue.
    """
    cleaned: List[ModelMessage] = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            parts = []
            for part in msg.parts:
                if isinstance(part, FilePart):
                    continue  # bytes live in the media store, not history
                if isinstance(part, ThinkingPart) and part.signature:
                    part = dataclasses.replace(part, signature=None)
                parts.append(part)
            if len(parts) != len(msg.parts):
                msg = dataclasses.replace(msg, parts=parts)
        cleaned.append(msg)
    return cleaned


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
            data = _model_message_adapter.dump_json(_sanitize(messages))
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
        # Purge binaries/signatures from memory too, so a long-lived process
        # doesn't accumulate megabyte-scale FileParts in RAM.
        self._storage[chat_id] = _sanitize(self._storage[chat_id])
        self._save(chat_id)
