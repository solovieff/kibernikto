import logging
import os
import sys
import traceback
from random import choice
from typing import List, Callable

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import User, BotCommand, Chat
from pydantic_settings import BaseSettings

from kibernikto.interactors import OpenAiExecutorConfig
from kibernikto.interactors.tools import Toolbox
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from ._executor_corral import init as init_ai_bot_corral, get_ai_executor_full, kill as kill_animals, get_temp_executor, \
    executor_exists


class TelegramSettings(BaseSettings):
    TG_BOT_KEY: str
    TG_MASTER_ID: int
    TG_MASTER_IDS: list = []
    TG_FRIEND_GROUP_IDS: list = []
    TG_MAX_MESSAGE_LENGTH: int = 4096
    TG_CHUNK_SENTENCES: int = 7
    TG_REACTION_CALLS: List[str] = ['honda', 'киберникто']
    TG_SAY_HI: bool = False
    TG_STICKER_LIST: List[str] = ["CAACAgIAAxkBAAELx29l_2OsQzpRWhmXTIMBM4yekypTOwACdgkAAgi3GQI1Wnpqru6xgTQE"]


TELEGRAM_SETTINGS = TelegramSettings()

smart_bot_class = None
TOOLS: List[Toolbox] = []

# Telegram bot
tg_bot: Bot = None
bot_me: User = None
dp = Dispatcher()
preprocessor = TelegramMessagePreprocessor()

COMMANDS: List[BotCommand] = []


def start(bot_class, tools=[], msg_preprocessor: TelegramMessagePreprocessor = None, commands=[]):
    """
    runs the executor polling the dispatcher for incoming messages

    :param tools: tools available for bots created by this dispatcher
    :type tools: List[Toolbox]
    :param bot_class: the bot class to use
    :type bot_class: Type[TelegramBot]
    :param msg_preprocessor: if we want to use custom message preprocessor
    :type msg_preprocessor: Type[TelegramMessagePreprocessor]
    :return:
    """
    global smart_bot_class
    global tg_bot
    global TOOLS
    global COMMANDS
    TOOLS = tools
    COMMANDS = commands

    global preprocessor
    if msg_preprocessor:
        preprocessor = msg_preprocessor

    print("\t")
    print('\t%-15s%-15s' % ("tg master:", TELEGRAM_SETTINGS.TG_MASTER_ID))
    print('\t%-15s%-15s' % ("tg masters:", TELEGRAM_SETTINGS.TG_MASTER_IDS))
    print('\t%-15s%-15s' % ("tg groups:", TELEGRAM_SETTINGS.TG_FRIEND_GROUP_IDS))
    print('\t%-15s%-15s' % ("dispatcher:", 'multi-user-and-group'))

    smart_bot_class = bot_class
    dp.startup.register(on_startup)
    tg_bot = Bot(token=TELEGRAM_SETTINGS.TG_BOT_KEY)
    from . import _default_handlers as dh
    dh.imported_ok()
    dp.run_polling(tg_bot, skip_updates=True)


async def async_start(bot_class, tools=[], msg_preprocessor=None, on_finish: Callable = None):
    """
    runs the executor polling the dispatcher for incoming messages

    :param tools: tools available for bots created by this dispatcher
    :type tools: List[Toolbox]
    :param bot_class: the bot class to use
    :type bot_class: Type[TelegramBot]
    :return:
    """
    global smart_bot_class
    global tg_bot
    global TOOLS
    TOOLS = tools

    global preprocessor
    if msg_preprocessor:
        preprocessor = msg_preprocessor

    smart_bot_class = bot_class
    dp.startup.register(on_startup)

    tg_bot = Bot(token=TELEGRAM_SETTINGS.TG_BOT_KEY)
    from . import _default_handlers as dh
    dh.imported_ok()
    await dp.start_polling(tg_bot, skip_updates=True)


async def on_startup(bot: Bot):
    try:
        global bot_me
        global COMMANDS

        if bot_me is None:
            bot_me = await bot.get_me()
            if COMMANDS:
                await bot.set_my_commands(COMMANDS)

        executor_config = OpenAiExecutorConfig(name=bot_me.first_name,
                                               reaction_calls=TELEGRAM_SETTINGS.TG_REACTION_CALLS,
                                               tools=TOOLS)

        init_ai_bot_corral(smart_bot_class=smart_bot_class,
                           master_id=TELEGRAM_SETTINGS.TG_MASTER_ID,
                           username=bot_me.username,
                           config=executor_config)

        if TELEGRAM_SETTINGS.TG_SAY_HI:
            master_id = TELEGRAM_SETTINGS.TG_MASTER_ID
            await send_random_sticker(chat_id=master_id)
            async with get_temp_executor(key_id=master_id) as hi_bot:
                hi_message = await hi_bot.heed_and_reply("Поприветствуй своего хозяина!")
                await tg_bot.send_message(chat_id=master_id, text=hi_message)
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
        logging.error(f"failed to start! \n{str(e)}")
        await kill_animals()
        await dp.stop_polling()
        exit(os.EX_CONFIG)


async def send_random_sticker(chat_id):
    sticker_id = choice(TELEGRAM_SETTINGS.TG_STICKER_LIST)

    # say hi to everyone
    await tg_bot.send_sticker(
        sticker=sticker_id,
        chat_id=chat_id)


def is_reply(message: types.Message):
    if message.reply_to_message and message.reply_to_message.from_user.id == tg_bot.id:
        return True
