import html
import logging

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart, Command
from aiogram.types import BotCommand

logger = logging.getLogger(__name__)

commands_router = Router(name="commands_router")

# Single source for the bot menu and /help.
COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(command="start", description="Start the bot"),
    BotCommand(command="help", description="Show this help message"),
    BotCommand(command="balance", description="Show your credits"),
    BotCommand(command="pay", description="Top up credits with Telegram Stars: /pay [stars]"),
    BotCommand(command="reset", description="Erase this chat's history and my notes (credits stay)"),
)
ADMIN_HELP = "Admins: /pay <±credits> <tg_id>, /balance <tg_id>"


async def set_bot_commands(bot: Bot) -> None:
    """Publish ``COMMANDS`` as the bot menu; cosmetic, so failures are only logged."""
    try:
        await bot.set_my_commands(list(COMMANDS))
    except TelegramAPIError as error:
        logger.warning("Bot menu not set: %s", error)


def help_text() -> str:
    """``/help`` body, HTML-escaped: the bot's default parse mode is HTML and ``<tg_id>`` is not a tag."""
    lines = (f"/{c.command} - {c.description}" for c in COMMANDS)
    return html.escape("\n".join(("Available commands:", *lines, ADMIN_HELP)), quote=False)


@commands_router.message(CommandStart())
async def cmd_start(message: types.Message):
    """Handle /start command."""
    await message.answer(
        "Hello! I am Kibernikto, your AI-powered assistant.\n"
        "Use /help to see available commands."
    )


@commands_router.message(Command("help"))
async def cmd_help(message: types.Message):
    """Handle /help command."""
    await message.answer(help_text())
