"""VkusVill as a credit-gated expert inside the multi-agent parent."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from pydantic_ai import RunContext
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent, default_model_settings
from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents
from kibernikto.ai.agent.telegram.deps import TelegramDeps

from .config import VKUSVILL_SETTINGS, VkusvillSettings
from .mcp import build_vkusvill_toolset
from .memory import basket_note, catalog_note, remember_basket
from .prompts import VKUSVILL_DELEGATED_INSTRUCTIONS

logger = logging.getLogger(__name__)

VKUSVILL_EXPERT_NAME = 'vkusvill'
VKUSVILL_EXPERT_DESCRIPTION = (
    'Покупки во ВкусВилле: найти продукты по каталогу, собрать корзину и вернуть ссылку на неё, '
    'персональные скидки и история заказов. Только личные покупки, не для общих вопросов.'
)


def _delegated_instructions(ctx: RunContext[TelegramDeps]) -> str:
    """Delegation contract plus the cart this chat built last time, when there is one."""
    return VKUSVILL_DELEGATED_INSTRUCTIONS + catalog_note(ctx.deps) + basket_note(ctx.deps)


def build_vkusvill_expert_agent(settings: VkusvillSettings = VKUSVILL_SETTINGS):
    """Tool-only shop agent for delegation: no history of its own, parent's deps type."""
    from kibernikto.ai.agent.utils import infer_kibernikto_model

    model = infer_kibernikto_model(settings.MODEL_NAME) if settings.MODEL_NAME else ...
    return build_kibernikto_agent(
        history_storage=None,
        history_size=settings.HISTORY_SIZE,
        deps_type=TelegramDeps,
        name=settings.NAME,
        persona=False,
        instructions=_delegated_instructions,
        model_settings={**default_model_settings(), 'parallel_tool_calls': settings.PARALLEL_TOOL_CALLS},
        toolsets=[build_vkusvill_toolset(settings, process_tool_call=remember_basket)],
        model=model,
    )


def build_vkusvill_expert(settings: VkusvillSettings = VKUSVILL_SETTINGS) -> SubAgent:
    """Delegation entry with the routing description the parent model reads."""
    return SubAgent(
        build_vkusvill_expert_agent(settings),
        name=VKUSVILL_EXPERT_NAME,
        description=VKUSVILL_EXPERT_DESCRIPTION,
        # Hard stop: a runaway search loop fails fast instead of burning the parent's credits.
        usage_limits=UsageLimits(tool_calls_limit=settings.MAX_TOOL_CALLS),
    )


def expert_allowed(*, credits: int | None, is_personal: bool, min_credits: int) -> bool:
    """Personal chats above the credit floor only; a group chat never sees the shop."""
    if not is_personal:
        return False
    if min_credits <= 0:
        return True
    return credits is not None and credits > min_credits


async def conversation_credits(ctx: RunContext[KiberniktoDeps]) -> int | None:
    """Credit balance of this run's conversation, or None when the run is not billable."""
    from kibernikto.storage.singletons import chat_data

    conversation_id = ctx.conversation_id
    if not conversation_id:
        return None
    deps = ctx.deps
    info = (deps.chat_info if isinstance(deps, KiberniktoDeps) else None) or await chat_data.load(conversation_id)
    return info.credits


@dataclass
class CreditGatedSubAgents(KiberniktoSubAgents):
    """Roster per run: gated experts disappear when the conversation may not use them."""

    gated_names: tuple[str, ...] = (VKUSVILL_EXPERT_NAME,)
    min_credits: int = 0

    async def for_run(self, ctx: RunContext[TelegramDeps]) -> KiberniktoSubAgents:
        run = await super().for_run(ctx)
        if not self.gated_names:
            return run
        credits = await conversation_credits(ctx)
        allowed = expert_allowed(
            credits=credits,
            is_personal=getattr(ctx.deps, 'is_personal', True),
            min_credits=self.min_credits,
        )
        if allowed:
            return run
        kept = [agent for agent in run.agents if _agent_name(agent) not in self.gated_names]
        if len(kept) == len(run.agents):
            return run
        gated = replace(run, agents=kept)
        gated._per_run = True  # noqa: SLF001 — the harness' own per-run copy contract
        gated._run_toolset = gated._make_toolset()  # noqa: SLF001
        logger.info('VkusVill expert withheld: credits=%s, personal=%s', credits, getattr(ctx.deps, 'is_personal', True))
        return gated


def _agent_name(sub_agent: SubAgent) -> str | None:
    return sub_agent.name or sub_agent.agent.name
