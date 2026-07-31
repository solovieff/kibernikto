"""Mini-filestore: durable media, tmp transit and the generated-image registry.

Everything lives under ``{APP_FILESTORE_LOCATION}``:

* ``media/{chat_id}/...`` — durable bytes (user photos, bot generations,
  later documents). History JSON only stores small references to these.
* ``tmp/...`` — transient files (e.g. voice before transcription), cleaned
  after use.
* ``media/{chat_id}/generated.json`` — public URLs of the last few bot-made
  images so the agent can re-inject them into context on later turns.
"""

import json
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

    def save(self, chat_id: int, data: bytes, ext: str = "bin", name: str | None = None) -> str:
        """Persist bytes under ``media/{chat_id}/``; returns a media ref ``"{chat_id}/{file}"``."""
        chat_dir = self._media_dir / str(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        file_name = name or f"{uuid.uuid4().hex[:12]}.{ext.lstrip('.')}"
        (chat_dir / file_name).write_bytes(data)
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

    # ── generated-image registry ───────────────────────────────────────────

    def remember_generated(self, chat_id: int, url: str, limit: int = 3) -> None:
        """Remember a generated image's public URL (most recent kept last)."""
        urls = [u for u in self.last_generated(chat_id) if u != url]
        urls.append(url)
        chat_dir = self._media_dir / str(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        (chat_dir / "generated.json").write_text(json.dumps(urls[-limit:]), encoding="utf-8")

    def last_generated(self, chat_id: int) -> list[str]:
        """Public URLs of recently generated images for a chat (oldest first)."""
        path = self._media_dir / str(chat_id) / "generated.json"
        if not path.exists():
            return []
        try:
            urls = json.loads(path.read_text(encoding="utf-8"))
            return urls if isinstance(urls, list) else []
        except Exception as exc:
            logger.warning("Failed to read generated registry %s: %s", path, exc)
            return []


#: Module-level singleton — shared by the preprocessor and the agent.
media_store = MediaFileStore()
