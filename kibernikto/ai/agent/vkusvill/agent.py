"""build_vkusvill_agent — plain Agent[TelegramDeps] wired to the VkusVill MCP toolset."""

import logging

from pydantic_ai import Agent, RunContext
from pydantic_ai.toolsets import AbstractToolset

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.kibernikto_agent import default_model_settings
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.singletons import history_storage

from .config import VKUSVILL_SETTINGS, VkusvillSettings
from .mcp import build_vkusvill_toolset
from .memory import basket_note, catalog_note, remember_basket
from .prompts import VKUSVILL_INSTRUCTIONS


def _instructions(ctx: RunContext[TelegramDeps]) -> str:
    """Static contract plus the cart this chat built last time, when there is one."""
    return VKUSVILL_INSTRUCTIONS + catalog_note(ctx.deps) + basket_note(ctx.deps)


def build_vkusvill_agent(
        *,
        history_storage: HistoryStorage | None = history_storage,
        toolset: AbstractToolset | None = None,
        settings: VkusvillSettings = VKUSVILL_SETTINGS,
        **kwargs,
) -> Agent[TelegramDeps]:
    """Shop assistant for Telegram: stock transport and history, VkusVill identity and tools."""
    if settings.MODEL_NAME is not None:
        kwargs.setdefault('model', infer_kibernikto_model(settings.MODEL_NAME))
    logging.getLogger('kibernikto').info(
        'VkusVill agent model: %s', settings.MODEL_NAME or AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME,
    )
    # Batched tool calls keep long shopping lists from crawling one search per step.
    kwargs.setdefault('model_settings', {
        **default_model_settings(), 'parallel_tool_calls': settings.PARALLEL_TOOL_CALLS,
    })
    return build_telegram_agent(
        history_storage=history_storage,
        history_size=settings.HISTORY_SIZE,
        name=settings.NAME,
        persona=False,
        instructions=_instructions,
        toolsets=[toolset or build_vkusvill_toolset(settings, process_tool_call=remember_basket)],
        **kwargs,
    )
