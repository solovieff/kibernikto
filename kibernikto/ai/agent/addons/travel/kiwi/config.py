"""Kiwi flight expert configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KiwiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_TRAVEL_KIWI_')

    # Kill switch: a disabled specialist is left out of the travel roster.
    ENABLED: bool = False
    MCP_URL: str = 'https://mcp.kiwi.com'
    MODEL_NAME: str | None = None
    MODEL_MAX_TOKENS: int = Field(default=8192, ge=1)
    MAX_TOOL_CALLS: int = Field(default=20, ge=1)


KIWI_SETTINGS = KiwiSettings()
