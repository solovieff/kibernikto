"""
Telegram-specialised Kibernikto agents.

The default conversation handlers always delegate to the module-level
:data:`kibernikto_telegram_agent` singleton, which is an instance of
:class:`TelegramAgent` built from the same env-derived configuration as the
core :data:`kibernikto.ai.agent.kibernikto_agent` singleton.

Projects that want to plug in their own subclass can either reassign the
singleton directly or call :func:`set_telegram_agent` before the dispatcher
starts.
"""

from .telegram_agent import (
    TelegramAgent,
    kibernikto_telegram_agent,
    set_telegram_agent,
)

__all__ = [
    "TelegramAgent",
    "kibernikto_telegram_agent",
    "set_telegram_agent",
]
