"""build_telegram_agent — plain Agent[TelegramDeps] with Kibernikto + Telegram capabilities."""

from pydantic_ai import Agent

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent
from kibernikto.ai.agent.core.persona import PersonaSource
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.singletons import history_storage

from .deps import TelegramDeps
from .identity import TelegramPersona
from .telegram_capability import TelegramCapability


def build_telegram_agent(
        *,
        history_storage: HistoryStorage | None = history_storage,
        persona_source: PersonaSource | None = None,
        reaction: str | None = ...,
        **kwargs,
) -> Agent[TelegramDeps]:
    """Kibernikto agent for Telegram: history, persona named after the bot, Telegram context and reactions."""
    kwargs.setdefault("deps_type", TelegramDeps)
    emoji = AGENT_KIBERNIKTO_SETTINGS.REACTION if reaction is ... else reaction
    kwargs["metadata"] = {**(kwargs.get("metadata") or {}), "reaction": emoji}
    kwargs["capabilities"] = [*(kwargs.get("capabilities") or ()), TelegramCapability()]
    return build_kibernikto_agent(history_storage=history_storage,
                                  persona_source=persona_source or TelegramPersona(), **kwargs)
