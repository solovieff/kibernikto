"""VkusVill shopping agent configuration — env-only via pydantic-settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.storage.config import STORAGE_SETTINGS

DEFAULT_MCP_URL = 'https://mcp.vkusvill.ru/mcp'
DEFAULT_SCOPES = ['catalog.search', 'purchase_history.read', 'discounts.view', 'recommendations.personalized']
DEFAULT_TOKEN_DIRNAME = 'vkusvill-oauth'


class VkusvillSettings(BaseSettings):
    """VkusVill MCP endpoint, credentials and the OAuth callback."""

    model_config = SettingsConfigDict(env_prefix='VKUSVILL_')

    NAME: str = Field(default='vkusvill', description='Agent name (ASCII, it rides attribution headers)')
    MCP_URL: str = Field(default=DEFAULT_MCP_URL, description='VkusVill MCP endpoint')
    MODEL_NAME: str | None = Field(
        default=None, description='Provider-prefixed model; unset = AGENT_KIBERNIKTO_MODEL_NAME',
    )
    AUTH_MODE: Literal['anonymous', 'oauth'] = Field(
        default='anonymous', description='anonymous: public catalog tools only; oauth: personalized tools',
    )
    OAUTH_CLIENT_ID: str | None = Field(default=None, description='From the VkusVill registration email')
    OAUTH_CLIENT_SECRET: str | None = Field(default=None, description='From the VkusVill registration email')
    OAUTH_SCOPES: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SCOPES), description='Requested OAuth scopes (JSON list in env)',
    )
    OAUTH_CALLBACK_PORT: int = Field(default=8765, description='Local OAuth callback port, must match redirect URI')
    OAUTH_CALLBACK_HOST: str = Field(default='localhost', description='Local OAuth callback host')
    OAUTH_TOKEN_DIR: str | None = Field(
        default=None, description='Token store dir; unset = FILESTORE/vkusvill-oauth',
    )

    @model_validator(mode='after')
    def _validate_oauth_credentials(self) -> 'VkusvillSettings':
        if self.AUTH_MODE == 'oauth' and not (self.OAUTH_CLIENT_ID and self.OAUTH_CLIENT_SECRET):
            raise ValueError(
                'VKUSVILL_AUTH_MODE=oauth requires VKUSVILL_OAUTH_CLIENT_ID and VKUSVILL_OAUTH_CLIENT_SECRET',
            )
        return self


VKUSVILL_SETTINGS = VkusvillSettings()


def resolve_token_dir(settings: VkusvillSettings = VKUSVILL_SETTINGS) -> Path:
    """Persistent OAuth token directory: explicit override or FILESTORE/vkusvill-oauth."""
    if settings.OAUTH_TOKEN_DIR:
        return Path(settings.OAUTH_TOKEN_DIR).expanduser()
    return Path(STORAGE_SETTINGS.FILESTORE_LOCATION).expanduser() / DEFAULT_TOKEN_DIRNAME
