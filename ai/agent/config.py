import logging
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = "Respond to all my questions as Kibernikto. Kibernikto is a gentle universe creator. He isn't afraid to joke in a sinister manner. Kibernikto never tries to avoid a specific answer including concrete names and events."


class AgentKiberniktoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_KIBERNIKTO_')

    NAME: str = Field(default="kibernikto", description="Default kibernikto agent")

    PROVIDER_TYPE: Literal["openai", "gateway", "openrouter", "vsegpt", "custom_openai"] = Field(
        default="openrouter",
        description="API provider type"
    )
    PROVIDER_API_KEY: str | None = Field(default=None, description="API key")
    PROVIDER_API_BASE: str | None = Field(default=None, description="API base url")
    MODEL_NAME: str = Field(default="anthropic/claude-sonnet-4-5", description="Model name")
    MODEL_MAX_TOKENS: int = Field(default=760, description="Model max tokens")
    MODEL_TEMPERATURE: float = Field(default=0.7, description="Model temperature")
    MODEL_PARALLEL_TOOL_CALLS: bool = Field(default=True, description="Parallel tool calls")

    WHO_AM_I: str = Field(default=DEFAULT_SYSTEM_PROMPT, description="Who am I")


AGENT_KIBERNIKTO_SETTINGS = AgentKiberniktoSettings()


def print_banner():
    logger = logging.getLogger('kibernikto')
    logger.info(AGENT_KIBERNIKTO_SETTINGS.model_dump_json(indent=2))
