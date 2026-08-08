import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from pydantic_ai.messages import ModelMessage

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.storage.base import _sanitize, _window, deserialize_messages, serialize_messages
from kibernikto.storage.config import STORAGE_SETTINGS

logger = logging.getLogger(__name__)


class FileStoreHistoryStorage:  # satisfies HistoryStorage (structural)
    """Durable JSON storage under ``{FILESTORE_LOCATION}/history/{name}/{chat_id}.json``.

    Standalone ``HistoryStorage`` impl — does **not** inherit ``MemoryHistoryStorage``.
    Keeps its own in-memory cache so repeated reads don't hit disk every turn.
    """

    def __init__(
        self,
        *,
        name: str,
        history_size: int = AGENT_KIBERNIKTO_SETTINGS.HISTORY_SIZE,
        keep_thinking: bool = AGENT_KIBERNIKTO_SETTINGS.KEEP_THINKING_IN_HISTORY,
        root: Path | None = None,
    ) -> None:
        self._root = root or Path(STORAGE_SETTINGS.FILESTORE_LOCATION).expanduser()
        self._name = name
        self._history_size = history_size
        self._keep_thinking = keep_thinking
        self._storage: Dict[int, List[ModelMessage]] = defaultdict(list)
        self._loaded: set[int] = set()

    # ── file helpers ─────────────────────────────────────────────────────────

    def _dir(self) -> Path:
        p = self._root / "history" / self._name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _path(self, chat_id: int) -> Path:
        return self._dir() / f"{chat_id}.json"

    async def _save(self, chat_id: int) -> None:
        messages = self._storage.get(chat_id)
        if messages is None:
            return
        try:
            raw = serialize_messages(_sanitize(messages, keep_thinking=self._keep_thinking))
            await asyncio.to_thread(self._path(chat_id).write_text, json.dumps(raw, ensure_ascii=False), "utf-8")
        except Exception as exc:
            logger.error("Failed to save history for chat %s: %s", chat_id, exc)

    async def _load(self, chat_id: int) -> None:
        if chat_id in self._loaded:
            return
        path = self._path(chat_id)
        if not path.exists():
            self._storage[chat_id] = []
            self._loaded.add(chat_id)
            return
        try:
            text = await asyncio.to_thread(path.read_text, "utf-8")
            messages = deserialize_messages(json.loads(text))
            # Migrate old files that still contain instructions / binaries.
            messages = _sanitize(messages, keep_thinking=self._keep_thinking)
            self._storage[chat_id] = messages
        except Exception as exc:
            logger.warning("Failed to load history for chat %s: %s", chat_id, exc)
            self._storage[chat_id] = []
        self._loaded.add(chat_id)

    # ── HistoryStorage ─────────────────────────────────────────────────────

    async def get_conversation(self, chat_id: int) -> List[ModelMessage]:
        await self._load(chat_id)
        return _window(self._storage[chat_id], self._history_size)

    async def add_messages(self, chat_id: int, messages: List[ModelMessage]) -> None:
        await self._load(chat_id)
        self._storage[chat_id].extend(messages)
        self._storage[chat_id] = _sanitize(self._storage[chat_id], keep_thinking=self._keep_thinking)
        await self._save(chat_id)
