"""Mini-filestore: durable media and tmp transit.

Everything lives under ``{APP_FILESTORE_LOCATION}``:

* ``media/{chat_id}/...`` — durable bytes (user photos, bot generations,
  later documents). History JSON only stores small references to these.
* ``tmp/...`` — transient files (e.g. voice before transcription), cleaned
  after use.
"""

import logging
import uuid
from pathlib import Path

from kibernikto.config import APP_SETTINGS

logger = logging.getLogger(__name__)


class MediaFileStore:
    """Per-chat file storage under ``{FILESTORE_LOCATION}/media`` plus ``tmp`` transit."""

    def __init__(self, root: Path | None = None) -> None:
        root = root or Path(APP_SETTINGS.FILESTORE_LOCATION).expanduser()
        self._media_dir = root / "media"
        self._tmp_dir = root / "tmp"

    # ── durable media ──────────────────────────────────────────────────────

    async def save(self, chat_id: int, data: bytes, ext: str = "bin", name: str | None = None) -> str:
        """Persist bytes under ``media/{chat_id}/``; returns a media ref ``"{chat_id}/{file}"``."""
        import asyncio
        chat_dir = self._media_dir / str(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        file_name = name or f"{uuid.uuid4().hex[:12]}.{ext.lstrip('.')}"
        await asyncio.to_thread((chat_dir / file_name).write_bytes, data)
        return f"{chat_id}/{file_name}"

    def path(self, media_ref: str) -> Path:
        """Resolve a media ref to a local path."""
        return self._media_dir / media_ref

    def read(self, media_ref: str) -> bytes:
        """Read the bytes of a media ref."""
        return self.path(media_ref).read_bytes()

    # ── tmp transit ────────────────────────────────────────────────────────

    def tmp_path(self, name: str) -> Path:
        """Return a path under ``tmp/`` (created on demand)."""
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        return self._tmp_dir / name

    @staticmethod
    def cleanup_tmp(path: Path) -> None:
        """Best-effort removal of a transient file."""
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Failed to clean tmp file %s: %s", path, exc)

#: Lazily resolved module-level singleton (PEP 562).
_media_store = None


def __getattr__(name: str):
    if name == "media_store":
        global _media_store
        if _media_store is None:
            from kibernikto.storage.factory import get_media_store
            _media_store = get_media_store()
        return _media_store
    raise AttributeError(name)
