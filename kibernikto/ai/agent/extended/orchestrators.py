"""SubAgents orchestrator — wires all experts into a credit-tiered, delegate_task-capable TelegramAgent."""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent

from pydantic_ai import ModelSettings
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness.exa import ExaSearch
from pydantic_ai_harness.researcher import DEFAULT_RESEARCHER_INSTRUCTIONS, Researcher
from pydantic_ai_harness.subagents import SubAgent, SubAgents
from pydantic_ai_harness.tool_output_limits import LocalFileStore

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.harness.chat_memory import chat_memory
from kibernikto.ai.agent.harness.credit_tier import CreditTier
from kibernikto.ai.agent.harness.image_agent import image_agent
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.config import STORAGE_SETTINGS
from kibernikto.storage.factory import get_history_storage

logger = logging.getLogger(__name__)

# Default experts. report_agent (needs VSEGPT_API_KEY) and scheduler_agent (no daemon) are opt-in:
# importing them builds their models, so they must never load as a side effect of this module.
_EXPERT_AGENTS = [image_agent]


def _web_capability(*, instructions: str | None = None) -> AbstractCapability:
    """Exa (native search + Exa page/deep search) when EXA_API_KEY is set, else the stock Researcher."""
    if os.getenv("EXA_API_KEY"):
        return ExaSearch(native=True, include_deep_search=True)
    # subagents=[]: our SubAgents already delegates (a second roster under id 'sub_agents' would clash).
    # Tool results over 10k chars go to disk; the model gets a preview + read_tool_result handle. Pruned after 1 day.
    spill = Path(STORAGE_SETTINGS.FILESTORE_LOCATION).expanduser() / "tool-output"
    store = LocalFileStore(base_dir=spill, cleanup_after=timedelta(days=1))
    return Researcher(subagents=[], instructions=instructions, store=store)


def _web_expert(model_name: str) -> KiberniktoAgent:
    """Web research delegate on its own (typically cheaper) model; keeps sourcing instructions."""
    return KiberniktoAgent(
        model=infer_kibernikto_model(model_name),
        name="web_researcher",
        description="Researches the web: searches, reads pages and answers with source links.",
        history_storage=None,
        capabilities=[_web_capability(instructions=DEFAULT_RESEARCHER_INSTRUCTIONS)],
    )


def _web_layout() -> tuple[list[AbstractCapability], list[SubAgent]]:
    """WEB_MODEL_NAME set: web is a delegated expert; unset: a parent capability on the tier model."""
    if model_name := AGENT_KIBERNIKTO_SETTINGS.WEB_MODEL_NAME:
        return [], [SubAgent(_web_expert(model_name))]
    return [_web_capability()], []  # Parent personality owns the tone, no Researcher instructions.


def _common_model_settings() -> ModelSettings:
    return ModelSettings(
        max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
        temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
        parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS,
    )


def _build_parent(delegates: list[SubAgent]) -> TelegramAgent:
    """Credit-tiered parent; the constructor model serves non-billable (peer envelope) runs."""
    name = AGENT_KIBERNIKTO_SETTINGS.NAME
    web_capabilities, web_experts = _web_layout()
    sub_agents = SubAgents(
        agents=[*(SubAgent(agent) for agent in _EXPERT_AGENTS), *web_experts, *delegates],
        agent_folders=None,
        contain_errors=True,
    )
    return TelegramAgent(
        model=infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME),
        model_settings=_common_model_settings(),
        name=name,
        history_storage=get_history_storage(name),
        # Memory/recall live on the parent: no extra LLM hop per remembered fact.
        capabilities=[CreditTier(), *chat_memory(name), *web_capabilities, sub_agents],
    )


def build_subagents_agent() -> TelegramAgent:
    """Build the credit-tiered parent with all experts wired via SubAgents delegation."""
    return _build_parent([])


def build_subagents_agent_with_tg_peers(
    peers: list[TelegramPeerAgent],
) -> TelegramAgent:
    """Build local experts plus explicitly supplied Telegram peers.

    No remote tokens, polling or network requests are needed at construction.
    Register the result with ``set_telegram_agent`` before running ``to_telegram``.
    Correlated answers are admitted automatically; no duplicate env allowlist.
    """
    # No timeout_seconds: the peer owns its deadline; an equal outer one races it and cancels mid-reply.
    return _build_parent([SubAgent(peer) for peer in peers])


# Pre-built singleton — used by --multi-agent flag.
kibernikto_subagents_agent = build_subagents_agent()