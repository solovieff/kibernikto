import logging

from aiogram import Router, types
from aiogram.filters import CommandStart, Command

logger = logging.getLogger(__name__)

commands_router = Router(name="commands_router")


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
    await message.answer(
        "Available commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message"
    )
