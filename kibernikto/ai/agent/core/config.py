import json
import logging
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = (
    "Respond to all my questions as Kibernikto. Kibernikto is a gentle universe creator. "
    "He isn't afraid to joke in a sinister manner. "
    "Kibernikto never tries to avoid a specific answer including concrete names and events."
)


class AgentKiberniktoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_KIBERNIKTO_')

    NAME: str = Field(default="kibernikto", description="Default kibernikto agent")
    REACTION: str | None = Field(
        default="👀", description="Parent agent's reaction on the user's message at run start; empty = none",
    )

    HISTORY_SIZE: int = Field(default=6, description="History size")
    KEEP_THINKING_IN_HISTORY: bool = Field(
        default=False,
        description="Keep model reasoning (ThinkingPart) in stored history; "
                    "off = drop (reasoning is replayed to the provider on every turn)",
    )
    MODEL_NAME: str = Field(default="openrouter:anthropic/claude-sonnet-5", description="Model name")
    FALLBACK_MODELS: list[str] = Field(
        default_factory=list,
        description="Fallback models in priority order; when set, default model is wrapped in FallbackModel",
    )
    IMAGE_MODEL_NAME: str | None = Field(
        default=None,
        description="Provider-prefixed model used by the image-generation sub-agent",
    )
    WEB_MODEL_NAME: str | None = Field(
        default=None,
        description="Set: web is a tool-less delegate on this search-native model (e.g. perplexity/sonar); "
                    "unset: Exa/Researcher tools on the tier model",
    )

    MODEL_MAX_TOKENS: int = Field(default=1300, description="Model max tokens")
    MODEL_TEMPERATURE: float = Field(default=0.3, description="Model temperature")
    MODEL_PARALLEL_TOOL_CALLS: bool = Field(default=True, description="Parallel tool calls")
    MODEL_MODALITIES: list[Literal['text', 'photo', 'audio']] = Field(
        default_factory=lambda: ['text'], description="Photo or audio modalities"
    )

    WHO_AM_I: str = Field(default=DEFAULT_SYSTEM_PROMPT, description="Who am I (Handlebars template allowed)")
    PERSONA_TEMPLATE: bool = Field(default=True, description="Render the persona as Handlebars; false = always plain text, `{{` stays literal")
    PERSONA_NAME: str | None = Field(default=None, description="{{name}} override; unset = Telegram bot name")
    PERSONA_TRAITS: dict[str, int] = Field(
        default_factory=dict, description='{{traits}} for the persona template, JSON: {"sarcasm": 10}'
    )

    # Credits & model balancing for the CreditTier capability
    TRIAL_CREDITS: int = Field(default=260, description="Initial credits for a new user")
    ALLOW_ZERO_CREDITS: bool = Field(default=True, description="Continue on the poor model at zero or negative credits")
    POOR_CREDITS: int = Field(default=30, description="Below this — poor model")
    RICH_CREDITS: int = Field(default=500, description="Above this — rich model")
    POOR_MODEL: str = Field(default="openrouter:google/gemini-2.5-flash", description="Model when credits are low")
    MEDIUM_MODEL: str = Field(
        default="openrouter:anthropic/claude-sonnet-5", description="Model when credits are medium",
    )
    RICH_MODEL: str = Field(default="openrouter:anthropic/claude-sonnet-5", description="Model when credits are high")


AGENT_KIBERNIKTO_SETTINGS = AgentKiberniktoSettings()


def agent_summary(name: str, agent_settings: AgentKiberniktoSettings = AGENT_KIBERNIKTO_SETTINGS) -> dict:
    """Non-secret summary of the agent that will actually serve requests (no keys, no personality text)."""
    s = agent_settings
    return {
        'MODE': name,
        'MODEL_NAME': s.MODEL_NAME,
        'IMAGE_MODEL_NAME': s.IMAGE_MODEL_NAME,
        'WEB_MODEL_NAME': s.WEB_MODEL_NAME,
        'POOR_MODEL': s.POOR_MODEL,
        'MEDIUM_MODEL': s.MEDIUM_MODEL,
        'RICH_MODEL': s.RICH_MODEL,
        'POOR_CREDITS': s.POOR_CREDITS,
        'RICH_CREDITS': s.RICH_CREDITS,
        'TRIAL_CREDITS': s.TRIAL_CREDITS,
        'ALLOW_ZERO_CREDITS': s.ALLOW_ZERO_CREDITS,
        'HISTORY_SIZE': s.HISTORY_SIZE,
        'MODEL_MAX_TOKENS': s.MODEL_MAX_TOKENS,
        'MODEL_TEMPERATURE': s.MODEL_TEMPERATURE,
        'MODEL_PARALLEL_TOOL_CALLS': s.MODEL_PARALLEL_TOOL_CALLS,
    }


def print_agent_summary(name: str) -> None:
    """Log the active agent's non-secret settings (call after the agent is selected)."""
    logger = logging.getLogger('kibernikto')
    logger.info(json.dumps(agent_summary(name), indent=2, ensure_ascii=False))
