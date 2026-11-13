"""VkusVill builders: standalone Telegram shop agent and the credit-gated delegated expert."""

import logging

from pydantic_ai import Agent, RunContext
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.harness.delegation import resolve_expert_model
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.singletons import history_storage

from ._prompts import VKUSVILL_DELEGATED_INSTRUCTIONS, VKUSVILL_INSTRUCTIONS
from .config import VKUSVILL_SETTINGS, VkusvillSettings
from .mcp import build_vkusvill_toolset
from .memory import ShopMemo, basket_note, catalog_note, remember_basket, shop_memory
from .tools import attach_shop_tools

VKUSVILL_EXPERT_NAME = 'vkusvill'
VKUSVILL_EXPERT_DESCRIPTION = (
    'Покупки во ВкусВилле: найти продукты по каталогу, собрать корзину и вернуть ссылку на неё, '
    'пересобрать последнюю корзину без указанных позиций, а также забыть её, когда заказ оформлен. '
    'Персональные скидки и история заказов — только после входа. Только личные покупки, не для общих вопросов.'
)


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
    return attach_shop_tools(build_telegram_agent(
        history_storage=history_storage,
        history_size=settings.HISTORY_SIZE,
        name=settings.NAME,
        persona=False,
        instructions=_instructions,
        toolsets=[toolset or build_vkusvill_toolset(settings, process_tool_call=remember_basket)],
        capabilities=[*(kwargs.pop('capabilities', ()) or ()), ShopMemo(), shop_memory(settings.NAME)],
        **kwargs,
    ))


def _delegated_instructions(ctx: RunContext[TelegramDeps]) -> str:
    """Delegation contract plus the cart this chat built last time, when there is one."""
    return VKUSVILL_DELEGATED_INSTRUCTIONS + catalog_note(ctx.deps) + basket_note(ctx.deps)


def build_vkusvill_expert_agent(settings: VkusvillSettings = VKUSVILL_SETTINGS):
    """Tool-only shop agent for delegation: no history of its own, parent's deps type."""
    return attach_shop_tools(build_kibernikto_agent(
        history_storage=None,
        history_size=settings.HISTORY_SIZE,
        deps_type=TelegramDeps,
        name=settings.NAME,
        metadata={'reaction': '👍'},
        persona=False,
        instructions=_delegated_instructions,
        model_settings={**default_model_settings(), 'parallel_tool_calls': settings.PARALLEL_TOOL_CALLS},
        toolsets=[build_vkusvill_toolset(settings, process_tool_call=remember_basket)],
        capabilities=[ShopMemo(), shop_memory(settings.NAME)],
        model=resolve_expert_model(None, settings.MODEL_NAME),
    ))


def build_vkusvill_expert(settings: VkusvillSettings = VKUSVILL_SETTINGS) -> SubAgent:
    """Delegation entry with the routing description the parent model reads."""
    return SubAgent(
        build_vkusvill_expert_agent(settings),
        name=VKUSVILL_EXPERT_NAME,
        description=VKUSVILL_EXPERT_DESCRIPTION,
        # Hard stop: a runaway search loop fails fast instead of burning the parent's credits.
        usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS),
    )
