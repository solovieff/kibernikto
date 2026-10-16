"""Run-scoped deps for the Telegram agent."""

from dataclasses import dataclass

from aiogram.types import Message

from kibernikto.ai.agent.core.deps import KiberniktoDeps


@dataclass
class TelegramDeps(KiberniktoDeps):
    """Telegram-only context on top of the transport-agnostic base."""

    is_personal: bool = True
    user_id: int | None = None
    username: str | None = None
    user_full_name: str | None = None
    app_chat_info: str | None = None
    app_chat_name: str | None = None
    message: Message | None = None
