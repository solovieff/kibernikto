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

    def __post_init__(self) -> None:
        if not self.is_admin and self.user_id is not None:
            from kibernikto.telegram.config import TELEGRAM_SETTINGS
            from kibernikto.telegram.utils.permissions import is_admin_id

            self.is_admin = TELEGRAM_SETTINGS.ADMIN_COMMANDS_ALLOWED and is_admin_id(self.user_id)
