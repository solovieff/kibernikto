import html
import logging

from aiogram import Bot, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart, Command
from aiogram.types import BotCommand, BufferedInputFile, ReplyParameters

from kibernikto.ai.speech import synthesize_speech
from kibernikto.storage.singletons import chat_data
from kibernikto.telegram.utils.voice import VOICE_PRIVACY_NOTICE, voice_messages_restricted

logger = logging.getLogger(__name__)

commands_router = Router(name="commands_router")

# Single source for the bot menu and /help.
COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(command="start", description="Start the bot"),
    BotCommand(command="help", description="Show this help message"),
    BotCommand(command="balance", description="Show your credits"),
    BotCommand(command="pay", description="Top up credits with Telegram Stars: /pay [stars]"),
    BotCommand(command="reset", description="Erase this chat's history and my notes (credits stay)"),
    BotCommand(command="toggle_voice", description="Switch between voice and text replies"),
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


@commands_router.message(Command('toggle_voice'))
async def cmd_toggle_voice(message: types.Message) -> None:
    """Switch voice replies for this chat; confirm the enabled mode with speech."""
    if message.from_user is None or message.from_user.is_bot:
        return
    cid = str(message.chat.id)
    info = await chat_data.load(cid)
    if info.response_mode == 'audio':
        info.response_mode = 'text'
        await chat_data.save(cid, info)
        await message.answer('Ок, теперь отвечаю текстом.')
        return
    try:
        audio = await synthesize_speech('Ок, теперь отвечаю голосом.')
    except Exception:
        logger.exception('Failed to enable voice replies')
        await message.answer('Не получилось включить голос. Пока отвечаю текстом.')
        return
    info = await chat_data.load(cid)
    info.response_mode = 'audio'
    await chat_data.save(cid, info)
    try:
        await message.bot.send_voice(
            chat_id=message.chat.id, voice=BufferedInputFile(audio, filename='voice.mp3'),
            reply_parameters=ReplyParameters(message_id=message.message_id),
        )
    except Exception as error:
        logger.exception('Failed to send voice confirmation')
        info = await chat_data.load(cid)
        info.response_mode = 'text'
        await chat_data.save(cid, info)
        notice = VOICE_PRIVACY_NOTICE if voice_messages_restricted(error) else 'Не получилось отправить голосовое. Пока отвечаю текстом.'
        await message.answer(notice)
