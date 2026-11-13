"""Settings for the gated travel coordinator and its Tutu source."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TravelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_TRAVEL_')

    ENABLED: bool = False
    MIN_CREDITS: int = Field(default=2000, ge=0)
    MODEL_NAME: str | None = None
    MODEL_MAX_TOKENS: int = Field(default=8192, ge=1)
    TUTU_MODEL_NAME: str | None = None
    TUTU_MODEL_MAX_TOKENS: int = Field(default=8192, ge=1)
    TUTU_MCP_URL: str = 'https://mcp.tutu.ru/mcp'
    MAX_TOOL_CALLS: int = Field(default=40, ge=1)


TRAVEL_SETTINGS = TravelSettings()
