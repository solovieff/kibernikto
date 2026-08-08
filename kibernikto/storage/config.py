"""Storage backend configuration — env-only via pydantic-settings."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_STORAGE_")

    FILESTORE_LOCATION: str = Field(default="~/.kibernikto", description="Root directory for file-based storage")
    DATA_BACKEND: Literal["file", "pg", "sqlite"] = Field(default="file")
    MEDIA_BACKEND: Literal["file", "s3"] = Field(default="file")

    PG_DSN: str | None = Field(default=None, description="postgresql+asyncpg://user:pass@host:5432/db")
    SQLITE_PATH: str = Field(default=":memory:", description="Path to sqlite file for DATA_BACKEND=sqlite")

    S3_ENDPOINT: str | None = Field(default=None)
    S3_BUCKET: str | None = Field(default=None)
    S3_REGION: str = Field(default="us-east-1")
    S3_ACCESS_KEY: str | None = Field(default=None)
    S3_SECRET_KEY: str | None = Field(default=None)


STORAGE_SETTINGS = StorageSettings()
