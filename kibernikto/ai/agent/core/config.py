import logging
from typing import Literal, List

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
    HISTORY_SIZE: int = Field(default=6, description="History size")
    MODEL_NAME: str = Field(default="anthropic/claude-sonnet-4.6", description="Model name")
    MODEL_MAX_TOKENS: int = Field(default=760, description="Model max tokens")
    MODEL_TEMPERATURE: float = Field(default=0.7, description="Model temperature")
    MODEL_PARALLEL_TOOL_CALLS: bool = Field(default=True, description="Parallel tool calls")
    MODEL_MODALITIES: List[Literal['text', 'photo', 'audio']] = Field(
        default=['text'], description="Photo or audio modalities"
    )

    WHO_AM_I: str = Field(default=DEFAULT_SYSTEM_PROMPT, description="Who am I")


AGENT_KIBERNIKTO_SETTINGS = AgentKiberniktoSettings()


def print_banner():
    logger = logging.getLogger('kibernikto')
    logger.info(AGENT_KIBERNIKTO_SETTINGS.model_dump_json(indent=2))
