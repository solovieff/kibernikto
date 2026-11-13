"""Travel coordinator with isolated, search-only Kiwi and Tutu delegates."""

from collections.abc import Sequence

from pydantic_ai.capabilities import AgentCapability
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.addons.travel.kiwi.agent import build_kiwi_expert
from kibernikto.ai.agent.addons.travel.tutu.agent import build_tutu_expert
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents, resolve_expert_model
from kibernikto.ai.agent.telegram.deps import TelegramDeps

from ._prompts import TRAVEL_INSTRUCTIONS
from .config import TRAVEL_SETTINGS, TravelSettings

# Coordinator only dispatches to tutu/kiwi; keep its tool-call ceiling tight.
COORDINATOR_MAX_TOOL_CALLS = 8


def build_travel_expert(*, settings: TravelSettings = TRAVEL_SETTINGS, model: Model | None = None,
                        experts: list[SubAgent] | None = None,
                        shared_capabilities: Sequence[AgentCapability[TelegramDeps]] = ()) -> SubAgent:
    """Build the coordinator; its isolated delegates share the caller's deps and usage."""
    children = experts if experts is not None else [build_tutu_expert(), build_kiwi_expert()]
    roster = KiberniktoSubAgents(agents=children, agent_folders=None, contain_errors=True,
                                shared_capabilities=shared_capabilities)
    agent = build_kibernikto_agent(
        model=resolve_expert_model(model, settings.MODEL_NAME), deps_type=TelegramDeps, name='travel',
        persona=False, history_storage=None, instructions=TRAVEL_INSTRUCTIONS, capabilities=[roster],
        metadata={'reaction': '👀'},
        model_settings={**default_model_settings(), 'max_tokens': settings.MODEL_MAX_TOKENS},
    )
    return SubAgent(agent, name='travel',
                    description=(
                        'Живой поиск путешествий: авиабилеты, отели, поезда, автобусы и электрички через Туту и Kiwi. '
                        'Только поиск предложений и расписаний, не для общих советов о городах, визах и погоде.'
                    ),
                    usage_limits=UsageLimits(tool_calls_limit=min(settings.MAX_TOOL_CALLS, COORDINATOR_MAX_TOOL_CALLS)))
