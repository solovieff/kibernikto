"""Travala hotel expert configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TravalaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_TRAVEL_TRAVALA_')

    # Kill switch: a disabled specialist is left out of the travel roster.
    ENABLED: bool = False
    MCP_URL: str = 'https://travel-mcp.travala.com/mcp'
    OAUTH_BASE_URL: str = 'https://travel-mcp.travala.com'
    # Cloudflare in front of Travala rejects non-browser user agents.
    USER_AGENT: str = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
    MODEL_NAME: str | None = None
    MODEL_MAX_TOKENS: int = Field(default=8192, ge=1)
    MAX_TOOL_CALLS: int = Field(default=20, ge=1)


TRAVALA_SETTINGS = TravalaSettings()
