"""Image hosting — publish bytes to a public URL the model can fetch.

The provider is selected by ``IMAGE_HOSTING_PROVIDER``: ``imgbb`` (default) or ``s3``.
Call sites only talk to :class:`ImageHosting`; ``publish`` returns ``None`` on failure.
"""

import logging
import mimetypes
import uuid
from datetime import UTC, datetime
from typing import Literal, Protocol

import aiohttp
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.storage.config import STORAGE_SETTINGS

logger = logging.getLogger(__name__)

_UPLOAD_TIMEOUT_SECONDS = 60
# Keys are random and never rewritten, so public caches may keep objects forever.
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
_MAGIC_TYPES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


class ImageHostingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IMAGE_")

    HOSTING_PROVIDER: Literal["imgbb", "s3"] = Field(default="imgbb", description="Public image hosting provider")
    STORAGE_API_KEY: str | None = Field(default=None, description="imgbb API key")
    STORAGE_EXPIRATION: int = Field(default=0, ge=0, description="imgbb TTL in seconds; 0 keeps history links alive")
    S3_BUCKET: str | None = Field(default=None, description="Public bucket; defaults to APP_STORAGE_S3_BUCKET")
    S3_PUBLIC_BASE_URL: str | None = Field(default=None, description="Public URL serving the bucket root")
    S3_PREFIX: str = Field(default="public", description="Key prefix; grant anonymous read on this prefix only")
    S3_ACL: str | None = Field(default=None, description="Optional canned ACL, e.g. public-read; many providers reject ACLs")

    @property
    def s3_bucket(self) -> str | None:
        return self.S3_BUCKET or STORAGE_SETTINGS.S3_BUCKET

    @model_validator(mode="after")
    def _validate_provider_requirements(self) -> "ImageHostingSettings":
        if self.HOSTING_PROVIDER != "s3":
            return self
        missing = [name for name, value in (
            ("IMAGE_S3_PUBLIC_BASE_URL", self.S3_PUBLIC_BASE_URL),
            ("IMAGE_S3_BUCKET or APP_STORAGE_S3_BUCKET", self.s3_bucket),
            ("APP_STORAGE_S3_ACCESS_KEY", STORAGE_SETTINGS.S3_ACCESS_KEY),
            ("APP_STORAGE_S3_SECRET_KEY", STORAGE_SETTINGS.S3_SECRET_KEY),
        ) if not value]
        if missing:
            raise ValueError(f"IMAGE_HOSTING_PROVIDER=s3 but missing: {', '.join(missing)}")
        if not self.S3_PUBLIC_BASE_URL.startswith(("https://", "http://")):
            raise ValueError("IMAGE_S3_PUBLIC_BASE_URL must be an absolute http(s) URL")
        return self


IMAGE_HOSTING_SETTINGS = ImageHostingSettings()


class ImageHosting(Protocol):
    """Publish image bytes and return a publicly fetchable URL, or ``None`` on failure."""

    async def publish(self, image_bytes: bytes, name: str) -> str | None: ...

    async def aclose(self) -> None: ...


def sniff_content_type(data: bytes, name: str) -> str:
    """Content type from magic bytes, then from *name*; generic binary as a last resort."""
    for magic, content_type in _MAGIC_TYPES:
        if data.startswith(magic):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


class ImgbbImageHosting:
    """imgbb.com hosting (https://api.imgbb.com/1/upload)."""

    URL = "https://api.imgbb.com/1/upload"

    def __init__(self, settings: ImageHostingSettings = IMAGE_HOSTING_SETTINGS) -> None:
        self._api_key = settings.STORAGE_API_KEY
        self._expiration = settings.STORAGE_EXPIRATION

    async def publish(self, image_bytes: bytes, name: str) -> str | None:
        if not self._api_key:
            logger.error("Image upload skipped: IMAGE_STORAGE_API_KEY is not set")
            return None
        payload: dict[str, str | bytes] = {"key": self._api_key, "image": image_bytes, "name": name}
        if self._expiration:
            payload["expiration"] = str(self._expiration)
        try:
            timeout = aiohttp.ClientTimeout(total=_UPLOAD_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.URL, data=payload) as response:
                    body = await response.json(content_type=None)
                    if response.status == 200:
                        return body["data"]["url"]
                    # Never log the payload: it carries the API key.
                    logger.error("Image upload failed: HTTP %s %s", response.status, body.get("error", body))
                    return None
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.error("Image upload failed: %r", exc)
            return None

    async def aclose(self) -> None:
        """Sessions are per upload; nothing to release."""


class S3ImageHosting:
    """Public image hosting in an S3-compatible bucket served at ``IMAGE_S3_PUBLIC_BASE_URL``.

    Keys are ``{prefix}/{yyyy}/{mm}/{uuid4}.{ext}``: unguessable and never overwritten. Public
    read access is configured outside Kibernikto (bucket policy, CDN or ``IMAGE_S3_ACL``).
    """

    def __init__(self, settings: ImageHostingSettings = IMAGE_HOSTING_SETTINGS) -> None:
        self._bucket = settings.s3_bucket
        self._base_url = (settings.S3_PUBLIC_BASE_URL or "").rstrip("/")
        self._prefix = settings.S3_PREFIX.strip("/")
        self._acl = settings.S3_ACL
        self._client = None

    def key_for(self, content_type: str) -> str:
        ext = _EXTENSIONS.get(content_type, "bin")
        now = datetime.now(UTC)
        return "/".join(p for p in (self._prefix, f"{now:%Y}", f"{now:%m}", f"{uuid.uuid4().hex}.{ext}") if p)

    def url_for(self, key: str) -> str:
        return f"{self._base_url}/{key}"

    async def _get_client(self):  # noqa: ANN202 — aiobotocore client type is generated at runtime
        if self._client is None:
            from kibernikto.storage.s3.client import open_async_client

            self._client = await open_async_client()
        return self._client

    async def publish(self, image_bytes: bytes, name: str) -> str | None:
        from botocore.exceptions import BotoCoreError, ClientError

        content_type = sniff_content_type(image_bytes, name)
        key = self.key_for(content_type)
        extra = {"ACL": self._acl} if self._acl else {}
        try:
            client = await self._get_client()
            await client.put_object(Bucket=self._bucket, Key=key, Body=image_bytes,
                                    ContentType=content_type, CacheControl=_IMMUTABLE_CACHE, **extra)
        except (BotoCoreError, ClientError) as exc:
            logger.error("Image upload to S3 failed for %s: %r", key, exc)
            return None
        return self.url_for(key)

    async def aclose(self) -> None:
        if self._client is None:
            return
        client, self._client = self._client, None
        await client.__aexit__(None, None, None)


def get_image_hosting(settings: ImageHostingSettings = IMAGE_HOSTING_SETTINGS) -> ImageHosting:
    """Build the provider selected by ``IMAGE_HOSTING_PROVIDER``."""
    match settings.HOSTING_PROVIDER:
        case "s3":
            return S3ImageHosting(settings)
        case _:
            return ImgbbImageHosting(settings)


def validate_image_hosting(settings: ImageHostingSettings = IMAGE_HOSTING_SETTINGS) -> None:
    """Startup check: HEAD the public S3 bucket; warn when imgbb has no key (photos would fail per message)."""
    if settings.HOSTING_PROVIDER == "s3":
        from kibernikto.storage.config import check_s3_bucket

        check_s3_bucket(settings.s3_bucket)
        logger.info("Image hosting: s3 bucket=%s base_url=%s", settings.s3_bucket, settings.S3_PUBLIC_BASE_URL)
        return
    if not settings.STORAGE_API_KEY:
        logger.warning("Image hosting: imgbb without IMAGE_STORAGE_API_KEY — photo publishing is disabled")
        return
    logger.info("Image hosting: imgbb")


#: Process-wide provider; the Telegram app shutdown hook closes it.
image_hosting: ImageHosting = get_image_hosting()
