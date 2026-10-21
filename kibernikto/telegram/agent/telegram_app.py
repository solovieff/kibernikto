"""Runnable Telegram bot application — built via TelegramApp.from_bridge()."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from kibernikto.telegram.peer_hub import PeerHub
from kibernikto.telegram.middleware.middleware_peer import PeerMiddleware

if TYPE_CHECKING:
    from kibernikto.telegram.bridge import TelegramBridge

logger = logging.getLogger(__name__)


class TelegramApp:
    """Ready-to-run Telegram bot: holds Bot + Dispatcher, provides run helpers."""

    def __init__(self, bot: Bot, dispatcher: Dispatcher) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self.peer_hub = PeerHub()
        self.dispatcher.message.outer_middleware(PeerMiddleware(self.peer_hub))
        self.dispatcher.edited_message.outer_middleware(PeerMiddleware(self.peer_hub, accept_replies=False))
        self.dispatcher.shutdown.register(self.peer_hub.close)

    def run_polling(self) -> None:  # noqa: ANN201 — blocks
        """Block and run long-polling (sync entry point)."""
        self.dispatcher.run_polling(self.bot)

    async def start_polling(self) -> None:
        """Start async long-polling (caller manages the event loop)."""
        await self.dispatcher.start_polling(self.bot)

    @classmethod
    def from_bridge(cls, bridge: TelegramBridge) -> TelegramApp:
        """Build a full Telegram bot serving *bridge* and register it as the active bridge."""
        from kibernikto.telegram.bridge import set_telegram_bridge
        set_telegram_bridge(bridge)

        from kibernikto.config import APP_SETTINGS
        from kibernikto.telegram.config import TELEGRAM_SETTINGS
        from kibernikto.telegram.handlers import commands_router, conversation_router, payments_router, reset_router
        from kibernikto.telegram.handlers.commands import set_bot_commands
        from kibernikto.telegram.middleware.middleware_firewall import FirewallMiddleware
        from kibernikto.telegram.middleware.middleware_service import (
            ErrorsMiddleware,
            ServiceMiddleware,
        )
        from kibernikto.telegram.middleware.middleware_subscription import (
            SubscriptionMiddleware,
        )

        bot = Bot(
            token=TELEGRAM_SETTINGS.BOT_KEY,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dispatcher = Dispatcher(name=APP_SETTINGS.INSTANCE_NAME)
        app = cls(bot, dispatcher)

        for mw in (ServiceMiddleware, ErrorsMiddleware, FirewallMiddleware, SubscriptionMiddleware):
            mw.apply_if_needed(dispatcher)

        dispatcher.include_router(commands_router)
        dispatcher.include_router(payments_router)
        dispatcher.include_router(reset_router)
        dispatcher.include_router(conversation_router)

        # Startup hook: DB tables + bot identity + optional greeting.
        async def _on_startup(bot: Bot) -> None:
            from kibernikto.storage.config import STORAGE_SETTINGS
            if STORAGE_SETTINGS.DATA_BACKEND in ("pg", "sqlite"):
                from kibernikto.storage.sql.engine import ensure_db_initialized
                await ensure_db_initialized()

            from kibernikto.ai.agent.telegram.identity import fetch_bot_identity, set_bot_identity

            identity = await fetch_bot_identity(bot)
            set_bot_identity(identity)
            await set_bot_commands(bot)
            logger.info("Bot started as @%s | %s", identity.username, identity.as_prompt())
            if TELEGRAM_SETTINGS.SAY_HI:
                from kibernikto.telegram.utils.conversation import send_random_sticker

                await send_random_sticker(
                    chat_id=TELEGRAM_SETTINGS.MASTER_ID,
                    sticker_list=TELEGRAM_SETTINGS.STICKER_IDS,
                    bot=bot,
                )

        dispatcher.startup.register(_on_startup)

        async def _on_shutdown(bot: Bot) -> None:
            from kibernikto.storage.factory import shutdown_storage
            from kibernikto.utils.image_hosting import image_hosting

            await shutdown_storage()
            await image_hosting.aclose()

        dispatcher.shutdown.register(_on_shutdown)

        return app
