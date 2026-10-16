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
    """Durable JSON storage under ``{FILESTORE_LOCATION}/history/{name}/{conversation_id}.json``.

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
        self._storage: Dict[str, List[ModelMessage]] = defaultdict(list)
        self._loaded: set[str] = set()

    # ── file helpers ─────────────────────────────────────────────────────────

    def _dir(self) -> Path:
        p = self._root / "history" / self._name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _path(self, conversation_id: str) -> Path:
        return self._dir() / f"{conversation_id}.json"

    async def _save(self, conversation_id: str) -> None:
        messages = self._storage.get(conversation_id)
        if messages is None:
            return
        try:
            raw = serialize_messages(_sanitize(messages, keep_thinking=self._keep_thinking))
            await asyncio.to_thread(self._path(conversation_id).write_text, json.dumps(raw, ensure_ascii=False), "utf-8")
        except Exception as exc:
            logger.error("Failed to save history for conversation %s: %s", conversation_id, exc)

    async def _load(self, conversation_id: str) -> None:
        if conversation_id in self._loaded:
            return
        path = self._path(conversation_id)
        if not path.exists():
            self._storage[conversation_id] = []
            self._loaded.add(conversation_id)
            return
        try:
            text = await asyncio.to_thread(path.read_text, "utf-8")
            messages = deserialize_messages(json.loads(text))
            # Migrate old files that still contain instructions / binaries.
            messages = _sanitize(messages, keep_thinking=self._keep_thinking)
            self._storage[conversation_id] = messages
        except Exception as exc:
            logger.warning("Failed to load history for conversation %s: %s", conversation_id, exc)
            self._storage[conversation_id] = []
        self._loaded.add(conversation_id)

    # ── HistoryStorage ─────────────────────────────────────────────────────

    async def get_conversation(self, conversation_id: str) -> List[ModelMessage]:
        cid = str(conversation_id)
        await self._load(cid)
        return _window(self._storage[cid], self._history_size)

    async def get_full_conversation(self, conversation_id: str, limit: int = 5000) -> List[ModelMessage]:
        cid = str(conversation_id)
        await self._load(cid)
        return self._storage[cid][-limit:]

    async def add_messages(self, conversation_id: str, messages: List[ModelMessage]) -> None:
        cid = str(conversation_id)
        await self._load(cid)
        self._storage[cid].extend(messages)
        self._storage[cid] = _sanitize(self._storage[cid], keep_thinking=self._keep_thinking)
        await self._save(cid)

    async def replace_messages(self, conversation_id: str, messages: List[ModelMessage]) -> None:
        cid = str(conversation_id)
        await self._load(cid)
        self._storage[cid] = _sanitize(list(messages), keep_thinking=self._keep_thinking)
        await self._save(cid)
