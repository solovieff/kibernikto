"""Tutu travel expert configuration."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TutuSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_TRAVEL_TUTU_', populate_by_name=True)

    MCP_URL: str = 'https://mcp.tutu.ru/mcp'
    MODEL_NAME: str | None = None
    MODEL_MAX_TOKENS: int = Field(default=8192, ge=1)
    # Shares the coordinator's `AGENT_TRAVEL_MAX_TOOL_CALLS` knob, as before the split.
    MAX_TOOL_CALLS: int = Field(default=40, ge=1, validation_alias=AliasChoices('AGENT_TRAVEL_TUTU_MAX_TOOL_CALLS',
                                                                                 'AGENT_TRAVEL_MAX_TOOL_CALLS'))


TUTU_SETTINGS = TutuSettings()
