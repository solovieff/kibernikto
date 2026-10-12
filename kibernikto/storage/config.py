"""Storage backend configuration — env-only via pydantic-settings."""

import logging
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_STORAGE_")

    FILESTORE_LOCATION: str = Field(default="~/.kibernikto", description="Root directory for file-based storage")
    DATA_BACKEND: Literal["file", "pg", "sqlite"] = Field(default="file")
    MEDIA_BACKEND: Literal["file", "s3"] = Field(default="file")

    PG_DSN: str | None = Field(default=None, description="postgresql+asyncpg://user:pass@host:5432/db")
    SQLITE_PATH: str = Field(default="~/.kibernikto/kibernikto.db", description="Path to sqlite file for DATA_BACKEND=sqlite")
    HISTORY_WINDOW_SLACK: int = Field(
        default=3,
        description="Multiplier for SQL history tail fetch: reads HISTORY_SIZE * slack rows so _window can align to a request boundary",
    )

    S3_ENDPOINT: str | None = Field(default=None)
    S3_BUCKET: str | None = Field(default=None)
    S3_REGION: str = Field(default="us-east-1")
    S3_ACCESS_KEY: str | None = Field(default=None)
    S3_SECRET_KEY: str | None = Field(default=None)
    S3_ADDRESSING_STYLE: Literal["path", "virtual"] = Field(default="path")
    S3_CHECKSUM_CALCULATION: Literal["when_supported", "when_required"] = Field(default="when_required")

    @model_validator(mode="after")
    def _validate_backend_requirements(self) -> "StorageSettings":
        if self.DATA_BACKEND == "pg" and not self.PG_DSN:
            raise ValueError("APP_STORAGE_DATA_BACKEND=pg but APP_STORAGE_PG_DSN is not set")
        if self.MEDIA_BACKEND == "s3":
            missing = [
                name for name in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(
                    f"APP_STORAGE_MEDIA_BACKEND=s3 but missing: {', '.join(f'APP_STORAGE_{m}' for m in missing)}"
                )
        return self


STORAGE_SETTINGS = StorageSettings()


def validate_storage() -> None:
    """Connectivity check for configured backends — call at startup (sync, no DB engine).

    Raises on failure so the bot crashes before polling starts, not after.
    DB table creation happens in ``telegram_app._on_startup`` (same event loop as polling).
    """
    s = STORAGE_SETTINGS

    if s.MEDIA_BACKEND == "s3":
        _check_s3(s)

    # Public image hosting is a media backend too: an unreachable bucket must fail before polling.
    from kibernikto.utils.image_hosting import validate_image_hosting

    validate_image_hosting()
    logger.info("Storage backends validated.")


def _check_s3(s: StorageSettings) -> None:
    """HEAD bucket to verify S3 credentials and endpoint."""
    check_s3_bucket(s.S3_BUCKET)


def check_s3_bucket(bucket: str | None) -> None:
    """HEAD *bucket* with the shared S3 credentials; raise ``OSError`` before polling on any failure."""
    try:
        from kibernikto.storage.s3.client import head_bucket_sync

        head_bucket_sync(bucket)
    except ImportError as exc:
        raise OSError("boto3 is required for S3 connectivity check — install it or use MEDIA_BACKEND=file") from exc
    except Exception as exc:
        raise OSError(f"S3 connection failed for bucket {bucket!r}: {exc}") from exc
