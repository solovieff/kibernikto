"""S3MediaStore — MediaFileStore backed by S3-compatible object storage."""

import logging
import uuid
from pathlib import Path

from kibernikto.config import APP_SETTINGS
from kibernikto.storage.config import STORAGE_SETTINGS

logger = logging.getLogger(__name__)


class S3MediaStore:
    """Per-chat media storage in S3-compatible bucket.

    Same interface as ``MediaFileStore``: ``save`` / ``path`` / ``read`` / ``tmp_path`` / ``cleanup_tmp``.
    Tmp is still local filesystem (transient voice data doesn't need S3).
    """

    def __init__(self) -> None:
        s = STORAGE_SETTINGS
        self._bucket = s.S3_BUCKET
        self._endpoint = s.S3_ENDPOINT
        self._region = s.S3_REGION
        self._access_key = s.S3_ACCESS_KEY
        self._secret_key = s.S3_SECRET_KEY
        self._tmp_dir = Path(APP_SETTINGS.FILESTORE_LOCATION).expanduser() / "tmp"
        self._client = None

    async def _get_client(self):
        """Lazy aioboto3 client."""
        if self._client is None:
            import aioboto3

            self._client = await aioboto3.Session().client(
                "s3",
                endpoint_url=self._endpoint,
                region_name=self._region,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
            ).__aenter__()
        return self._client

    async def save(self, chat_id: int, data: bytes, ext: str = "bin", name: str | None = None) -> str:
        """Upload bytes to S3 under ``media/{chat_id}/{file}``; returns S3 key."""
        client = await self._get_client()
        file_name = name or f"{uuid.uuid4().hex[:12]}.{ext.lstrip('.')}"
        key = f"media/{chat_id}/{file_name}"
        await client.put_object(Bucket=self._bucket, Key=key, Body=data)
        return key

    async def path(self, media_ref: str) -> Path:
        """S3 doesn't have local paths — return a temp download or raise.
        Use ``read`` for actual byte access; this exists for interface compat only."""
        raise NotImplementedError("S3MediaStore.path is not supported — use read()")

    async def read(self, media_ref: str) -> bytes:
        """Read bytes from S3."""
        client = await self._get_client()
        resp = await client.get_object(Bucket=self._bucket, Key=media_ref)
        return await resp["Body"].read()

    # ── tmp transit (local, same as file variant) ─────────────────────────

    def tmp_path(self, name: str) -> Path:
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        return self._tmp_dir / name

    @staticmethod
    def cleanup_tmp(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Failed to clean tmp file %s: %s", path, exc)
