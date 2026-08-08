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
    SQLITE_PATH: str = Field(default=":memory:", description="Path to sqlite file for DATA_BACKEND=sqlite")
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

    logger.info("Storage backends validated.")


def _check_s3(s: StorageSettings) -> None:
    """HEAD bucket to verify S3 credentials and endpoint."""
    try:
        import boto3
        from botocore.config import Config as BotoConfig
        client = boto3.client(
            "s3",
            endpoint_url=s.S3_ENDPOINT,
            region_name=s.S3_REGION,
            aws_access_key_id=s.S3_ACCESS_KEY,
            aws_secret_access_key=s.S3_SECRET_KEY,
            config=BotoConfig(
                s3={"addressing_style": s.S3_ADDRESSING_STYLE},
                request_checksum_calculation=s.S3_CHECKSUM_CALCULATION,
            ),
        )
        client.head_bucket(Bucket=s.S3_BUCKET)
    except ImportError:
        raise OSError("boto3 is required for S3 connectivity check — install it or use MEDIA_BACKEND=file")
    except Exception as exc:
        raise OSError(f"S3 connection failed: {exc}") from exc
