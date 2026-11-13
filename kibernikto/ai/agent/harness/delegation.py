"""Delegation capability: stock harness ``SubAgents`` with Kibernikto's roster and credit gating."""

from __future__ import annotations

import logging
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace

from pydantic_ai import RunContext
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai_harness.subagents import SubAgent, SubAgents

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.utils import infer_kibernikto_model

logger = logging.getLogger(__name__)

# Roster preamble replacing the harness default: decide, delegate with full context, answer.
DELEGATION_GUIDE = (
    "You have access to LLM agents for solving various tasks via the `delegate_task` function.\n"
    "When receiving a request, you must:\n"
    "1. Determine if any agents can be useful for completing the task.\n"
    "2. Use these agents to obtain necessary information or perform actions. An agent does not see this "
    "conversation: pass it everything it needs (exact question, links, names, dates, the user's language).\n"
    "3. Provide the user with an accurate and helpful response to their request.\n"
    "Do not bother agents if you can do the job yourself with GOOD quality. You cannot know anything current "
    "or recent yourself: never answer such questions from memory."
)


def allow_tools(toolset: AbstractToolset, allowed: AbstractSet[str]) -> AbstractToolset:
    """Expose only explicitly reviewed tool names, hiding future server additions."""
    def allow(_ctx: RunContext, tool: ToolDefinition) -> bool:
        return tool.name in allowed

    return toolset.filtered(allow)


def resolve_expert_model(model: Model | None, model_name: str | None) -> Model | object:
    """Use an explicit model override, else resolve ``model_name``, else fall back to default (``...``)."""
    if model is not None:
        return model
    return infer_kibernikto_model(model_name) if model_name else ...


def expert_allowed(*, credits: int | None, is_personal: bool, min_credits: int) -> bool:
    """Personal chats above the credit floor only; a group chat never sees gated experts."""
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
class KiberniktoSubAgents(SubAgents):
    """Stock ``SubAgents`` delegation with ``DELEGATION_GUIDE`` instead of the harness roster text."""

    def get_instructions(self) -> str | None:
        # The stock text is None when delegation is off (max depth) or nobody is listed: keep that contract.
        if super().get_instructions() is None:
            return None
        roster = "\n".join(_roster_line(sub_agent) for sub_agent in self.agents)
        return f"{DELEGATION_GUIDE}\n\nAvailable agents:\n{roster}"


@dataclass
class CreditGatedSubAgents(KiberniktoSubAgents):
    """Roster per run: gated experts disappear when the conversation may not use them."""

    gated_names: tuple[str, ...] = ()
    min_credits: int = 0
    gated_thresholds: dict[str, int] = field(default_factory=dict)

    async def for_run(self, ctx: RunContext[object]) -> KiberniktoSubAgents:
        run = await super().for_run(ctx)
        thresholds = {name: self.min_credits for name in self.gated_names}
        thresholds.update(self.gated_thresholds)
        if not thresholds:
            return run
        credits = await conversation_credits(ctx)
        personal = getattr(ctx.deps, "is_personal", True)

        def permitted(agent: SubAgent) -> bool:
            name = _agent_name(agent)
            if name is None or name not in thresholds:
                return True
            return expert_allowed(credits=credits, is_personal=personal, min_credits=thresholds[name])

        kept = [agent for agent in run.agents if permitted(agent)]
        if len(kept) == len(run.agents):
            return run
        gated = replace(run, agents=kept)
        gated._per_run = True  # noqa: SLF001 — the harness' own per-run copy contract
        gated._run_toolset = gated._make_toolset()  # noqa: SLF001
        logger.info("Restricted experts withheld: credits=%s, personal=%s", credits, personal)
        return gated


def _agent_name(sub_agent: SubAgent) -> str | None:
    return sub_agent.name or sub_agent.agent.name


def _roster_line(sub_agent: SubAgent) -> str:
    name = sub_agent.name or sub_agent.agent.name
    description = sub_agent.description or sub_agent.agent.description
    return f"- {name}: {description}" if description else f"- {name}"
