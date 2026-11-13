"""Search-only Kiwi flight expert for the delegated agent roster."""

from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.harness.delegation import allow_tools, resolve_expert_model
from kibernikto.ai.agent.telegram.deps import TelegramDeps

from ._prompts import KIWI_DESCRIPTION, KIWI_INSTRUCTIONS
from .config import KIWI_SETTINGS, KiwiSettings

KIWI_ALLOWED_TOOLS = frozenset({'search-flight'})


def search_only_toolset(toolset: AbstractToolset) -> AbstractToolset:
    """Expose flight search only; do not allow unsolicited feedback or future write tools."""
    return allow_tools(toolset, KIWI_ALLOWED_TOOLS)


def build_kiwi_expert(
        *, settings: KiwiSettings = KIWI_SETTINGS, model: Model | None = None,
        toolset: AbstractToolset | None = None,
) -> SubAgent:
    """Build a transport-free expert; no network request at construction."""
    tools = toolset if toolset is not None else MCPToolset(settings.MCP_URL)
    agent = build_kibernikto_agent(
        model=resolve_expert_model(model, settings.MODEL_NAME),
        deps_type=TelegramDeps,
        name='kiwi',
        metadata={'reaction': '😎'},
        persona=False,
        history_storage=None,
        instructions=KIWI_INSTRUCTIONS,
        model_settings={**default_model_settings(), 'max_tokens': settings.MODEL_MAX_TOKENS},
        toolsets=[search_only_toolset(tools)],
    )
    return SubAgent(agent, name='kiwi', description=KIWI_DESCRIPTION,
                    usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS))
