"""SubAgents orchestrator — wires all experts into a delegate_task-capable KiberniktoExtended."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent

from pydantic_ai import ModelSettings
from pydantic_ai.capabilities import WebSearch
from pydantic_ai_harness.subagents import SubAgent, SubAgents

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.extended.kibernikto_extended import KiberniktoExtended
from kibernikto.ai.agent.harness.conversation_agent import conversation_agent
from kibernikto.ai.agent.harness.image_agent import image_agent
from kibernikto.ai.agent.harness.report_agent import report_agent
from kibernikto.ai.agent.harness.scheduler_agent import scheduler_agent
from kibernikto.ai.agent.harness.web_agent import web_agent
from kibernikto.ai.agent.utils import infer_kibernikto_model

logger = logging.getLogger(__name__)

# All expert sub-agents available to the orchestrator.
_EXPERT_AGENTS = [web_agent, image_agent, conversation_agent] #, report_agent


def _common_model_settings() -> ModelSettings:
    return ModelSettings(
        max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
        temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
        parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS,
    )


def build_subagents_agent() -> KiberniktoExtended:
    """Build a KiberniktoExtended with all experts wired via SubAgents delegation."""
    model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)
    sub_agents = SubAgents(
        agents=[SubAgent(agent) for agent in _EXPERT_AGENTS],
        agent_folders=None,
        contain_errors=True,
    )

    return KiberniktoExtended(
        model=model,
        model_settings=_common_model_settings(),
        name=AGENT_KIBERNIKTO_SETTINGS.NAME,
        capabilities=[WebSearch(), sub_agents],
    )


def build_subagents_agent_with_tg_peers(
    peers: list[TelegramPeerAgent],
) -> KiberniktoExtended:
    """Build local experts plus explicitly supplied Telegram peers.

    No remote tokens, polling or network requests are needed at construction.
    Register the result with ``set_telegram_agent`` before running ``to_telegram``.
    Correlated answers are admitted automatically; no duplicate env allowlist.
    """
    sub_agents = SubAgents(
        agents=[
            *(SubAgent(agent) for agent in _EXPERT_AGENTS),
            *(SubAgent(peer) for peer in peers),
        ],
        agent_folders=None,
        contain_errors=True,
    )
    return KiberniktoExtended(
        model=infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME),
        model_settings=_common_model_settings(),
        name=AGENT_KIBERNIKTO_SETTINGS.NAME,
        capabilities=[WebSearch(), sub_agents],
    )


# Pre-built singleton — used by --multi-agent flag.
kibernikto_subagents_agent = build_subagents_agent()