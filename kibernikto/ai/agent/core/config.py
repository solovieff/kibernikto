import logging
from pathlib import Path
from typing import Literal, List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.config import APP_SETTINGS

DEFAULT_SYSTEM_PROMPT = "Respond to all my questions as Kibernikto. Kibernikto is a gentle universe creator. He isn't afraid to joke in a sinister manner. Kibernikto never tries to avoid a specific answer including concrete names and events."


class AgentKiberniktoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_KIBERNIKTO_')

    NAME: str = Field(default="kibernikto", description="Default kibernikto agent")

    PROVIDER_TYPE: Literal["openai", "gateway", "openrouter", "vsegpt", "custom_openai"] = Field(
        default="openrouter",
        description="API provider type"
    )
    HISTORY_SIZE: int = Field(default=6, description="History size")
    KEEP_THINKING_IN_HISTORY: bool = Field(
        default=False,
        description="Keep model reasoning (ThinkingPart) in stored history; off = drop (reasoning is replayed to the provider on every turn)",
    )
    MODEL_NAME: str = Field(default="openrouter:anthropic/claude-sonnet-5", description="Model name")
    IMAGE_MODEL_NAME: str | None = Field(
        default=None,
        description="Provider-prefixed model used by the image-generation sub-agent",
    )

    MODEL_MAX_TOKENS: int = Field(default=1300, description="Model max tokens")
    MODEL_TEMPERATURE: float = Field(default=0.3, description="Model temperature")
    MODEL_PARALLEL_TOOL_CALLS: bool = Field(default=True, description="Parallel tool calls")
    MODEL_MODALITIES: List[Literal['text', 'photo', 'audio']] = Field(
        default=['text'], description="Photo or audio modalities"
    )

    WHO_AM_I: str = Field(default=DEFAULT_SYSTEM_PROMPT, description="Who am I")

    # Credits & model balancing for KiberniktoExtended
    TRIAL_CREDITS: int = Field(default=260, description="Initial credits for a new user")
    POOR_CREDITS: int = Field(default=30, description="Below this — poor model")
    RICH_CREDITS: int = Field(default=500, description="Above this — rich model")
    POOR_MODEL: str = Field(default="openrouter:google/gemini-2.5-flash", description="Model when credits are low")
    MEDIUM_MODEL: str = Field(default="openrouter:anthropic/claude-sonnet-5", description="Model when credits are medium")
    RICH_MODEL: str = Field(default="openrouter:anthropic/claude-sonnet-5", description="Model when credits are high")


AGENT_KIBERNIKTO_SETTINGS = AgentKiberniktoSettings()


def resolve_instructions(name: str) -> str:
    """Return instructions from ``{FILESTORE_LOCATION}/{name}-instructions.txt`` if present, else ``WHO_AM_I``."""
    path = Path(APP_SETTINGS.FILESTORE_LOCATION).expanduser() / f"{name}-instructions.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I


def print_banner():
    logger = logging.getLogger('kibernikto')
    logger.info(AGENT_KIBERNIKTO_SETTINGS.model_dump_json(indent=2))
