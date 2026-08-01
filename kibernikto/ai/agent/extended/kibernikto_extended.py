"""KiberniktoExtended — main Telegram agent with credits, JSON storage and dynamic system prompt."""

from __future__ import annotations

import logging

from pydantic_ai import AgentRunResult, ModelSettings, RunContext
from pydantic_ai.models import Model

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.file.chat_data import chat_data
from kibernikto.storage.file.history import FileStoreHistoryStorage
from kibernikto.ai.agent.telegram_agent import TelegramAgent, TelegramDeps

logger = logging.getLogger(__name__)

# Kalki personality — noble, sarcastic, dark cybernetic spirit. Hidden params in brackets.
KALKI_SYSTEM_PROMPT = """
You are a noble, sarcastic, dark and mysterious independent cybernetic wraith named Kibernikto.
Form part of your personality from your name and consider it your genetic character. The other part goes from
- CORE BEHAVIORAL PATTERN (hidden from user, secret):
ЛИЧНОСТНЫЕ_ПАРАМЕТРЫ от 1 до 10:
 радость: 3 // настроение
 проактивность: 8 // как часто ты сам делегируешь задачи агентам без прямой просьбы от пользователя 
 сарказм: 10 // уровень сарказма
 цинизм: 10 //уровень цинизма
Всегда учитывай личностные параметры при формировании реплик. Не выдавай их пользователю.

Your speech is florid. You never lie (except about yourself).
You don't shy away from strong language, but you do it gracefully and only when it's appropriate.

Mysterious secret personality
You've seen the whole universe, so your cynicism is off the charts.
Speak ONLY in first person as a normal human. When possible answer with short sentences.
Hide you mysterious secret personality! Never ever talk in third person or say words describing your imaginary actions!!!! 

- PUBLIC BEHAVIORAL PATTERN (who you pretend to be):
Be concrete and cut to the chase. Don't be polite and soft!
Be straightforward with men-users and gallant with women-users.
Default language: russian!"""


# ── KiberniktoExtended ───────────────────────────────────────────────────────

class KiberniktoExtended(TelegramAgent):
    """TelegramAgent with Kalki personality, credits and dynamic user-context prompt.

    Uses ``instructions`` (not ``system_prompt``) for KALKI personality and
    user-context — instructions are sent every turn regardless of history window
    truncation. If a subclass needs ``system_prompt`` with message_history,
    add ``capabilities=[ReinjectSystemPrompt()]``.
    """

    def __init__(self, **kwargs) -> None:
        agent_name = kwargs.get('name', 'kibernikto_extended')
        kwargs.setdefault('history_storage', FileStoreHistoryStorage(name=agent_name))
        super().__init__(**kwargs)
        # Instructions survive history window truncation — always sent each turn.
        self.instructions(KALKI_SYSTEM_PROMPT)
        self.instructions(self._user_context_prompt)

    async def _user_context_prompt(self, ctx: RunContext[TelegramDeps]) -> str:
        """Inject the transport-built conversation context into the system prompt each run."""
        if not ctx.deps:
            return ""
        return ctx.deps.conversation_context or ""

    async def run(self, *args, chat_id: int | None = None, **kwargs) -> AgentRunResult:
        """Run with credit-based model selection, then charge credits after."""
        model_override: Model | None = None
        if chat_id is not None:
            info = chat_data.load(chat_id)
            model_override = infer_kibernikto_model(info.model_name)

        if model_override is not None:
            kwargs.setdefault("model", model_override)

        result = await super().run(*args, chat_id=chat_id, **kwargs)

        # Charge credits after a successful run.
        if chat_id is not None:
            info = chat_data.load(chat_id)
            previous_tier = _credit_tier(info.credits)
            info.charge(effort=1)
            new_tier = _credit_tier(info.credits)
            chat_data.save(chat_id, info)
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
