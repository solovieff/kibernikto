"""Search-only Travala hotel expert for the travel coordinator."""

from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.harness.delegation import allow_tools, resolve_expert_model
from kibernikto.ai.agent.telegram.deps import TelegramDeps

from ._prompts import TRAVALA_DESCRIPTION, TRAVALA_INSTRUCTIONS
from .auth import TravalaAuth
from .config import TRAVALA_SETTINGS, TravalaSettings

# Wallet, booking, cancel and account tools stay hidden: real USDC moves through them.
TRAVALA_ALLOWED_TOOLS = frozenset({'travala_search_hotel', 'travala_search_package'})


def search_only_toolset(toolset: AbstractToolset) -> AbstractToolset:
    """Expose hotel search only; booking and wallet tools are never reachable."""
    return allow_tools(toolset, TRAVALA_ALLOWED_TOOLS)


def build_travala_expert(
        *, settings: TravalaSettings = TRAVALA_SETTINGS, model: Model | None = None,
        toolset: AbstractToolset | None = None,
) -> SubAgent:
    """Build a transport-free expert; no network request until the first run."""
    tools = toolset if toolset is not None else MCPToolset(
        settings.MCP_URL, auth=TravalaAuth(settings), headers={'User-Agent': settings.USER_AGENT},
        tool_error_behavior='failed',
    )
    agent = build_kibernikto_agent(
        model=resolve_expert_model(model, settings.MODEL_NAME),
        deps_type=TelegramDeps,
        name='travala',
        metadata={'reaction': '🤩'},
        persona=False,
        history_storage=None,
        instructions=TRAVALA_INSTRUCTIONS,
        model_settings={**default_model_settings(), 'max_tokens': settings.MODEL_MAX_TOKENS},
        toolsets=[search_only_toolset(tools)],
    )
    return SubAgent(agent, name='travala', description=TRAVALA_DESCRIPTION,
                    usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS))
