"""Multi-agent Kibernikto for Telegram — credit-tiered parent delegating to experts via delegate_task."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic_ai import ModelSettings
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.harness.chat_memory import chat_memory
from kibernikto.ai.agent.harness.credit_tier import CreditTier
from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents
from kibernikto.ai.agent.harness.image_agent import image_agent
from kibernikto.ai.agent.harness.web import web_layout
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.factory import get_history_storage

from .agent_reaction import AgentReaction
from .telegram_agent import TelegramAgent

if TYPE_CHECKING:
    from .peer_agent import TelegramPeerAgent

logger = logging.getLogger(__name__)

# Default experts. report_agent (needs VSEGPT_API_KEY) and scheduler_agent (no daemon) are opt-in:
# importing them builds their models, so they must never load as a side effect of this module.
_EXPERT_AGENTS = [image_agent]


def build_multi_agent() -> TelegramAgent:
    """Build the credit-tiered parent with all experts wired via SubAgents delegation."""
    return _build_parent([])


def build_multi_agent_with_tg_peers(
        peers: list[TelegramPeerAgent],
) -> TelegramAgent:
    """Build local experts plus explicitly supplied Telegram peers.

    No remote tokens, polling or network requests are needed at construction.
    Register the result with ``set_telegram_agent`` before running ``to_telegram``.
    Correlated answers are admitted automatically; no duplicate env allowlist.
    """
    # No timeout_seconds: the peer owns its deadline; an equal outer one races it and cancels mid-reply.
    return _build_parent([SubAgent(peer) for peer in peers])


def _build_parent(delegates: list[SubAgent]) -> TelegramAgent:
    """Credit-tiered parent; the constructor model serves non-billable (peer envelope) runs."""
    name = AGENT_KIBERNIKTO_SETTINGS.NAME
    web_capabilities, web_experts = web_layout()
    sub_agents = KiberniktoSubAgents(
        agents=[*(SubAgent(agent) for agent in _EXPERT_AGENTS), *web_experts, *delegates],
        agent_folders=None,
        contain_errors=True,
        shared_capabilities=[AgentReaction()],  # Each delegate marks the user's message with its own emoji.
    )
    return TelegramAgent(
        model=infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME),
        model_settings=_common_model_settings(),
        name=name,
        reaction=AGENT_KIBERNIKTO_SETTINGS.REACTION,
        history_storage=get_history_storage(name),
        # Memory/recall live on the parent: no extra LLM hop per remembered fact.
        capabilities=[CreditTier(), *chat_memory(name), *web_capabilities, sub_agents],
    )


def _common_model_settings() -> ModelSettings:
    return ModelSettings(
        max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
        temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
        parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS,
    )


# Pre-built singleton — used by --multi-agent flag.
kibernikto_multi_agent = build_multi_agent()
