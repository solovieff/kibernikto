"""Run-scoped deps for the Telegram agent."""

from dataclasses import dataclass
from typing import Optional

from aiogram.types import Message

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.storage.models import ConversationInfo


@dataclass
class TelegramDeps(KiberniktoDeps):
    """Telegram-flavoured deps — adds chat/user context for tools."""

    is_personal: bool = True
    chat_id: Optional[int] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    user_full_name: Optional[str] = None
    app_chat_info: Optional[str] = None
    app_chat_name: Optional[str] = None
    message: Optional[Message] = None
    timezone: Optional[str] = None
    billable: bool = True  # False for peer-envelope requests: no credit tiering or charging.
    chat_info: ConversationInfo | None = None  # Run-start snapshot of chat_data; read-only, writers reload.
