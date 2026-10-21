"""Multi-agent Kibernikto for Telegram — credit-tiered parent delegating to experts via delegate_task."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic_ai import Agent, ModelSettings
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.harness.conversation_memory import ConversationMemory
from kibernikto.ai.agent.harness.credit_tier import CreditTier
from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents
from kibernikto.ai.agent.harness.image_agent import image_agent
from kibernikto.ai.agent.harness.web import web_layout
from kibernikto.ai.agent.utils import build_kibernikto_model, infer_kibernikto_model
from kibernikto.storage.factory import get_history_storage

from .agent_reaction import AgentReaction
from .deps import TelegramDeps
from .telegram_agent import build_telegram_agent

if TYPE_CHECKING:
    from .peer_agent import TelegramPeerAgent

logger = logging.getLogger(__name__)

# Default experts. report_agent (needs VSEGPT_API_KEY) and scheduler_agent (no daemon) are opt-in:
# importing them builds their models, so they must never load as a side effect of this module.
_EXPERT_AGENTS = [image_agent]


def build_multi_agent() -> Agent[TelegramDeps]:
    """Build the credit-tiered parent with all experts wired via SubAgents delegation."""
    return _build_parent([])


def build_multi_agent_with_tg_peers(
        peers: list[TelegramPeerAgent],
) -> Agent[TelegramDeps]:
    """Build local experts plus explicitly supplied Telegram peers.

    No remote tokens, polling or network requests are needed at construction.
    Wrap the result in TelegramBridge and pass it to TelegramApp.from_bridge.
    Correlated answers are admitted automatically; no duplicate env allowlist.
    """
    # No timeout_seconds: the peer owns its deadline; an equal outer one races it and cancels mid-reply.
    return _build_parent([SubAgent(peer) for peer in peers])


def _build_parent(delegates: list[SubAgent]) -> Agent[TelegramDeps]:
    """Credit-tiered parent; the constructor model serves non-billable (peer envelope) runs."""
    name = AGENT_KIBERNIKTO_SETTINGS.NAME
    if image_agent.model is None:
        image_agent.model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.POOR_MODEL)
    web_capabilities, web_experts = web_layout()
    sub_agents = KiberniktoSubAgents(
        agents=[*(SubAgent(agent) for agent in _EXPERT_AGENTS), *web_experts, *delegates],
        agent_folders=None,
        contain_errors=True,
        shared_capabilities=[AgentReaction()],  # Each delegate marks the user's message with its own emoji.
    )
    return build_telegram_agent(
        model=build_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME, AGENT_KIBERNIKTO_SETTINGS.FALLBACK_MODELS),
        model_settings=_common_model_settings(),
        name=name,
        reaction=AGENT_KIBERNIKTO_SETTINGS.REACTION,
        history_storage=get_history_storage(name),
        # Memory/recall live on the parent: no extra LLM hop per remembered fact.
        capabilities=[CreditTier(), ConversationMemory(name), *web_capabilities, sub_agents],
    )


def _common_model_settings() -> ModelSettings:
    return ModelSettings(
        max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
        temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
        parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS,
    )
