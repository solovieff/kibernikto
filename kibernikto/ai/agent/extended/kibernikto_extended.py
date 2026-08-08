"""KiberniktoExtended — main Telegram agent with credits, JSON storage and dynamic system prompt."""

from __future__ import annotations

import logging

from pydantic_ai import AgentRunResult, ModelSettings
from pydantic_ai.models import Model

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.file.chat_data import chat_data
from kibernikto.storage.factory import get_history_storage
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
from kibernikto.ai.agent.telegram.deps import TelegramDeps

logger = logging.getLogger(__name__)

# ── KiberniktoExtended ───────────────────────────────────────────────────────

class KiberniktoExtended(TelegramAgent):
    """TelegramAgent with Kalki personality, credits and dynamic user-context prompt.

    Uses ``instructions`` (not ``system_prompt``) for KALKI personality and
    user-context — instructions are sent every turn regardless of history window
    truncation. If a subclass needs ``system_prompt`` with message_history,
    add ``capabilities=[ReinjectSystemPrompt()]``.
    """

    def __init__(self, **kwargs) -> None:
        agent_name = kwargs.get('name', AGENT_KIBERNIKTO_SETTINGS.NAME)
        kwargs.setdefault('history_storage', get_history_storage(agent_name))
        super().__init__(**kwargs)

    async def run(self, *args, chat_id: int | None = None, **kwargs) -> AgentRunResult:
        """Run with credit-based model selection, then charge credits after."""
        model_override: Model | None = None
        if chat_id is not None:
            info = await chat_data.load(chat_id)
            model_override = infer_kibernikto_model(info.model_name)

        if model_override is not None:
            kwargs.setdefault("model", model_override)

        result = await super().run(*args, chat_id=chat_id, **kwargs)

        # Charge credits after a successful run.
        if chat_id is not None:
            info = await chat_data.load(chat_id)
            previous_tier = _credit_tier(info.credits)
            info.charge(effort=1)
            new_tier = _credit_tier(info.credits)
            await chat_data.save(chat_id, info)
            if new_tier != previous_tier:
                logger.info("Model tier changed for chat %s: %s -> %s", chat_id, previous_tier, new_tier)

        return result


def _credit_tier(credits: int) -> str:
    """Return 'poor' / 'medium' / 'rich' for the current credit balance."""
    s = AGENT_KIBERNIKTO_SETTINGS
    if credits < s.POOR_CREDITS:
        return "poor"
    if credits >= s.RICH_CREDITS:
        return "rich"
    return "medium"


# ── Singleton instance ────────────────────────────────────────────────────────

_model: Model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)
_model_settings: ModelSettings = ModelSettings(
    max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
    temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
    parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS,
)

# kibernikto_multi_agent = KiberniktoExtended(
#    model=_model,
#    model_settings=_model_settings,
#    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
# )
