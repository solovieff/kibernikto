"""build_vkusvill_agent — plain Agent[TelegramDeps] wired to the VkusVill MCP toolset."""

from pydantic_ai import Agent
from pydantic_ai.toolsets import AbstractToolset

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.singletons import history_storage

from .config import VKUSVILL_SETTINGS, VkusvillSettings
from .mcp import build_vkusvill_toolset
from .prompts import VKUSVILL_INSTRUCTIONS


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
    return build_telegram_agent(
        history_storage=history_storage,
        name=settings.NAME,
        persona=False,
        instructions=VKUSVILL_INSTRUCTIONS,
        toolsets=[toolset or build_vkusvill_toolset(settings)],
        **kwargs,
    )
