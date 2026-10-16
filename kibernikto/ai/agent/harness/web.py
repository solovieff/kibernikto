"""Web access: a tool-less delegate on a search-native model, or Exa/Researcher tools on the parent."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from pydantic_ai import capabilities
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness.exa import ExaSearch
from pydantic_ai_harness.researcher import Researcher
from pydantic_ai_harness.subagents import SubAgent
from pydantic_ai_harness.tool_output_limits import LocalFileStore

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.config import STORAGE_SETTINGS

WEB_EXPERT_NAME = "web-agent"
WEB_EXPERT_DESCRIPTION = (
    "Live internet. Use it for page URLs, actual data (news, exchange rates, prices, weather, events, "
    "schedules) and simple web search."
)
WEB_EXPERT_INSTRUCTIONS = (
    "Answer the task from live web search. Be brief: the facts, how current they are, "
    "some full URLs of your sources."
)
# Parent-side Exa: stock guidance asks to survey widely and read pages in full, too much for a chat bot.
WEB_SEARCH_GUIDANCE = (
    "You have web tools. For simple facts (rates, prices, weather, news) run one `web_search` and answer "
    "from its excerpts. Use `get_page` only for a URL the user gave or when excerpts lack the answer. "
    "Cite the URLs you relied on."
)


def web_layout() -> tuple[list[AbstractCapability], list[SubAgent]]:
    """(parent capabilities, delegates): WEB_MODEL_NAME set → one delegate; unset → tools on the tier model."""
    if model_name := AGENT_KIBERNIKTO_SETTINGS.WEB_MODEL_NAME:
        return [], [SubAgent(_web_expert(model_name))]
    return [_web_tools()], []


def _web_expert(model_name: str) -> KiberniktoAgent:
    """Search-native model (e.g. perplexity/sonar) does the searching: no tools, no persona."""
    return KiberniktoAgent(
        model=infer_kibernikto_model(model_name),
        name=WEB_EXPERT_NAME,
        description=WEB_EXPERT_DESCRIPTION,
        instructions=WEB_EXPERT_INSTRUCTIONS,
        history_storage=None,
        persona=False,
        reaction="👨‍💻",
    )


def _web_tools() -> AbstractCapability:
    """Exa (native search + Exa pages) when EXA_API_KEY is set, else the stock Researcher."""
    if os.getenv("EXA_API_KEY"):
        return ExaSearch(native=True, include_deep_search=False, guidance=WEB_SEARCH_GUIDANCE)
    # subagents=[]: our SubAgents already delegates (a second roster under id 'sub_agents' would clash).
    # Tool results over 10k chars go to disk; the model gets a preview + read_tool_result handle. Pruned after 1 day.
    spill = Path(STORAGE_SETTINGS.FILESTORE_LOCATION).expanduser() / "tool-output"
    store = LocalFileStore(base_dir=spill, cleanup_after=timedelta(days=1))
    return Researcher(subagents=[], instructions=None, store=store)  # Parent personality owns the tone.
