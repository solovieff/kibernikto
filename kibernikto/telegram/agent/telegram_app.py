"""Runnable Telegram bot application — built via TelegramApp.from_agent()."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

if TYPE_CHECKING:
    from aiogram.types import User

    from kibernikto.ai.agent.telegram_agent import TelegramAgent

logger = logging.getLogger(__name__)

# Set after the bot starts; read by permissions.py.
bot_me: Optional[User] = None


class TelegramApp:
    """Ready-to-run Telegram bot: holds Bot + Dispatcher, provides run helpers."""

    def __init__(self, bot: Bot, dispatcher: Dispatcher) -> None:
        self.bot = bot
        self.dispatcher = dispatcher

    def run_polling(self) -> None:  # noqa: ANN201 — blocks
        """Block and run long-polling (sync entry point)."""
        self.dispatcher.run_polling(self.bot)

    async def start_polling(self) -> None:
        """Start async long-polling (caller manages the event loop)."""
        await self.dispatcher.start_polling(self.bot)

    @classmethod
    def from_agent(cls, agent: TelegramAgent) -> TelegramApp:
        """Build a full Telegram bot wired to *agent*.

        Creates Bot + Dispatcher, registers middlewares / routers, hooks startup.
        Does NOT call set_telegram_agent() — caller is responsible for that.
        """
        from kibernikto.config import APP_SETTINGS
        from kibernikto.telegram.config import TELEGRAM_SETTINGS
        from kibernikto.telegram.handlers import commands_router, conversation_router
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

        for mw in (ServiceMiddleware, ErrorsMiddleware, FirewallMiddleware, SubscriptionMiddleware):
            mw.apply_if_needed(dispatcher)

        dispatcher.include_router(commands_router)
        dispatcher.include_router(conversation_router)

        app = cls(bot, dispatcher)

        # Startup hook: fetch bot identity + optional greeting.
        async def _on_startup(bot: Bot) -> None:
            global bot_me
            bot_me = await bot.get_me()
            logger.info("Bot started as @%s", bot_me.username)
            if TELEGRAM_SETTINGS.SAY_HI:
                from kibernikto.telegram.utils.conversation import send_random_sticker

                await send_random_sticker(
                    chat_id=TELEGRAM_SETTINGS.MASTER_ID,
                    sticker_list=TELEGRAM_SETTINGS.STICKER_IDS,
                    bot=bot,
                )

        dispatcher.startup.register(_on_startup)

        return app