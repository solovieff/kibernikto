import logging
from collections.abc import Sequence

from pydantic_ai import Agent, ModelSettings
from pydantic_ai.messages import UserContent

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.persona import (
    PERSONA_INSTRUCTION, PersonaFirst, PersonaSource, StaticPersona, compile_persona, persona_source_text,
)
from kibernikto.ai.agent.harness.conversation_history import ConversationHistory
from kibernikto.ai.agent.utils import build_kibernikto_model, with_attribution
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.singletons import history_storage
from kibernikto.utils.time_utils import DEFAULT_TIMEZONE, get_user_date

logger = logging.getLogger(__name__)


def default_model_settings() -> ModelSettings:
    """Default model settings built from ``AGENT_KIBERNIKTO_SETTINGS``."""
    return ModelSettings(
        max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
        temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
        parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS,
    )


model_settings: ModelSettings = default_model_settings()


def KiberniktoAgent(
        *,
        model: object = ...,
        history_storage: HistoryStorage | None = None,
        persona_source: PersonaSource | None = None,
        persona: bool = True,
        reaction: str | None = None,
        **kwargs,
) -> Agent[KiberniktoDeps]:
    """Factory creating a standard pydantic_ai ``Agent`` with Kibernikto capabilities."""
    kwargs.setdefault("name", AGENT_KIBERNIKTO_SETTINGS.NAME)
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

    caps = list(kwargs.get("capabilities") or ())
    conv_hist = ConversationHistory(
        history_storage,
        history_size=AGENT_KIBERNIKTO_SETTINGS.HISTORY_SIZE,
        keep_thinking=AGENT_KIBERNIKTO_SETTINGS.KEEP_THINKING_IN_HISTORY,
    )
    caps.append(conv_hist)
    if persona:
        caps.append(PersonaFirst())
    kwargs["capabilities"] = caps

    if not callable(settings := kwargs.get("model_settings")):
        kwargs["model_settings"] = with_attribution(settings, kwargs.get("name"))

    agent = Agent(**kwargs)
    agent.reaction = reaction
    agent._reaction = reaction
    agent.history_storage = history_storage
    agent._history_storage = history_storage
    agent.active_runs = conv_hist.active_runs
    agent._active_runs = conv_hist.active_runs
    agent._conv_history = conv_hist

    orig_run = agent.run

    async def run_wrapper(
            user_prompt: str | Sequence[UserContent] | None = None,
            *,
            conversation_id: str | int | None = None,
            **run_kwargs,
    ):
        cid = str(conversation_id) if conversation_id is not None and conversation_id != "" else None
        if cid is not None and user_prompt is not None and conv_hist.steer_active_run(cid, user_prompt, run_kwargs.get("deps")):
            return None
        res = await orig_run(user_prompt, conversation_id=cid if cid is not None else "", **run_kwargs)
        if res is not None:
            ConversationHistory._materialize_attachments(res, run_kwargs.get("deps"))
        return res

    agent.run = run_wrapper

    if persona:
        text = compile_persona(persona_source_text(agent.name), persona_source or StaticPersona())
        agent.instructions(name=PERSONA_INSTRUCTION)(text)

    def current_date_prompt(ctx) -> str:
        timezone = ctx.deps.timezone if isinstance(ctx.deps, KiberniktoDeps) else None
        return f"Current date: {get_user_date(timezone or DEFAULT_TIMEZONE)}."

    agent.instructions(current_date_prompt)
    return agent
