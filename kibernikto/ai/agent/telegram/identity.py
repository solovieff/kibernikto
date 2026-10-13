"""Bot identity — fetched once at startup (getMe + descriptions), read from memory every run."""

import logging
from dataclasses import dataclass

from aiogram import Bot

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.persona import DEFAULT_PERSONA_NAME, StaticPersona

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BotIdentity:
    """Raw Telegram bot facts; restart to pick up BotFather edits."""

    username: str | None = None
    full_name: str | None = None
    short_description: str | None = None
    description: str | None = None

    def as_prompt(self) -> str:
        """Compact parameters line; no "You are" — the persona owns that phrasing."""
        parts = [
            f"username: @{self.username}" if self.username else "",
            f"display_name: {self.full_name}" if self.full_name else "",
            f"short_description: {self.short_description}" if self.short_description else "",
            f"description: {self.description}" if self.description else "",
        ]
        text = " | ".join(filter(None, parts))
        return f"[Your Telegram bot parameters] {text}" if text else ""


_bot_identity: BotIdentity | None = None


def set_bot_identity(identity: BotIdentity | None) -> None:
    """Store the bot's identity; called by the Telegram startup hook."""
    global _bot_identity
    _bot_identity = identity


def get_bot_identity() -> BotIdentity | None:
    return _bot_identity


@dataclass(frozen=True, slots=True)
class TelegramPersona(StaticPersona):
    """``{{name}}`` = explicit → ``AGENT_KIBERNIKTO_PERSONA_NAME`` → Telegram bot name → default."""

    def resolve_name(self) -> str:
        identity = get_bot_identity()
        bot_name = identity.full_name if identity else None
        return self.name or AGENT_KIBERNIKTO_SETTINGS.PERSONA_NAME or bot_name or DEFAULT_PERSONA_NAME


async def fetch_bot_identity(bot: Bot) -> BotIdentity:
    """getMe is required; descriptions are best-effort (missing rights or API hiccups)."""
    me = await bot.get_me()
    short_description = description = None
    try:
        short_description = (await bot.get_my_short_description()).short_description or None
    except Exception as exc:
        logger.warning("Bot short description unavailable: %s", exc)
    try:
        description = (await bot.get_my_description()).description or None
    except Exception as exc:
        logger.warning("Bot description unavailable: %s", exc)
    return BotIdentity(username=me.username, full_name=me.full_name,
                       short_description=short_description, description=description)
