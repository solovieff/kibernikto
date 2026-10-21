"""Transport-free Kibernikto agent builder on standard pydantic-ai Agent and capabilities."""

from pydantic_ai import Agent, ModelSettings

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.persona import PersonaCapability, PersonaSource
from kibernikto.ai.agent.harness.conversation_history import ConversationHistory
from kibernikto.ai.agent.utils import build_kibernikto_model, with_attribution
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.singletons import history_storage


def default_model_settings() -> ModelSettings:
    """Default model settings built from ``AGENT_KIBERNIKTO_SETTINGS``."""
    return ModelSettings(
        max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
        temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
        parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS,
    )


model_settings: ModelSettings = default_model_settings()


def build_kibernikto_agent(
        *,
        model: object = ...,
        history_storage: HistoryStorage | None = None,
        persona_source: PersonaSource | None = None,
        persona: bool = True,
        **kwargs,
) -> Agent[KiberniktoDeps]:
    """Build a standard ``pydantic_ai.Agent`` wired with ``ConversationHistory`` and ``PersonaCapability``."""
    name = kwargs.setdefault("name", AGENT_KIBERNIKTO_SETTINGS.NAME)
    kwargs.setdefault("deps_type", KiberniktoDeps)
    if model is ...:
        kwargs["model"] = build_kibernikto_model(
            AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME,
            AGENT_KIBERNIKTO_SETTINGS.FALLBACK_MODELS,
        )
    else:
        kwargs["model"] = model

    if "model_settings" not in kwargs:
        kwargs["model_settings"] = default_model_settings()
    if not callable(settings := kwargs.get("model_settings")):
        kwargs["model_settings"] = with_attribution(settings, name)

    conv_history = ConversationHistory(
        history_storage,
        history_size=AGENT_KIBERNIKTO_SETTINGS.HISTORY_SIZE,
        keep_thinking=AGENT_KIBERNIKTO_SETTINGS.KEEP_THINKING_IN_HISTORY,
    )
    persona_cap = PersonaCapability(name, source=persona_source, include_persona=persona)
    kwargs["capabilities"] = [*(kwargs.get("capabilities") or ()), conv_history, persona_cap]

    return Agent(**kwargs)
