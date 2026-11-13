"""Travel coordinator with isolated, search-only Kiwi and Tutu delegates."""

from collections.abc import Sequence
from datetime import datetime, timezone

from pydantic_ai import ModelRetry
from pydantic_ai.capabilities import AgentCapability
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.addons.travel.kiwi.agent import build_kiwi_expert
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents, allow_tools, resolve_expert_model
from kibernikto.ai.agent.telegram.deps import TelegramDeps

from ._prompts import TRAVEL_INSTRUCTIONS, TUTU_INSTRUCTIONS
from .config import TRAVEL_SETTINGS, TravelSettings

# Coordinator only dispatches to tutu/kiwi; keep its tool-call ceiling tight.
COORDINATOR_MAX_TOOL_CALLS = 8

TUTU_ALLOWED_TOOLS = frozenset({
    'search_hotels', 'search_avia', 'search_rail', 'search_bus', 'search_etrain', 'search_multitransport',
    'get_offer_details', 'get_rail_seatmap', 'get_avia_instructions', 'get_rail_instructions',
    'get_bus_instructions', 'get_etrain_instructions', 'get_hotels_instructions',
    'get_multitransport_instructions', 'create_checkout_link', 'fetch_resource',
})


def elapsed_minutes(departure: str, arrival: str) -> int:
    """Minutes between ISO-8601 timestamps with explicit time zones, including connections."""
    try:
        start = datetime.fromisoformat(departure)
        end = datetime.fromisoformat(arrival)
    except ValueError as exc:
        raise ModelRetry('Use ISO-8601 timestamps with UTC offsets') from exc
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ModelRetry('Both timestamps must include a UTC offset')
    seconds = (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds()
    if seconds < 0:
        raise ModelRetry('Arrival cannot precede departure')
    return int(seconds // 60)


def tutu_toolset(toolset: AbstractToolset) -> AbstractToolset:
    """Allow explicitly reviewed read-only tools and URL generation, never passenger registration."""
    return allow_tools(toolset, TUTU_ALLOWED_TOOLS)


def build_tutu_expert(*, settings: TravelSettings = TRAVEL_SETTINGS, model: Model | None = None,
                      toolset: AbstractToolset | None = None) -> SubAgent:
    """Build a Tutu delegate without network access until a run."""
    remote = toolset if toolset is not None else MCPToolset(settings.TUTU_MCP_URL)
    agent = build_kibernikto_agent(
        model=resolve_expert_model(model, settings.TUTU_MODEL_NAME), deps_type=TelegramDeps, name='tutu',
        persona=False, history_storage=None, instructions=TUTU_INSTRUCTIONS, metadata={'reaction': '🤓'},
        model_settings={**default_model_settings(), 'max_tokens': settings.TUTU_MODEL_MAX_TOKENS},
        toolsets=[tutu_toolset(remote), FunctionToolset([elapsed_minutes])],
    )
    return SubAgent(agent, name='tutu', description='Туту: авиа, отели, поезда, автобусы и электрички.',
                    usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS))


def build_travel_expert(*, settings: TravelSettings = TRAVEL_SETTINGS, model: Model | None = None,
                        experts: list[SubAgent] | None = None,
                        shared_capabilities: Sequence[AgentCapability[TelegramDeps]] = ()) -> SubAgent:
    """Build the coordinator; its isolated delegates share the caller's deps and usage."""
    children = experts if experts is not None else [build_tutu_expert(settings=settings), build_kiwi_expert()]
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
