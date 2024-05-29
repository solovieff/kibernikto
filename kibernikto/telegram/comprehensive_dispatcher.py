import logging
import os
import sys
import traceback
from random import choice
from typing import List, Callable

from aiogram import Bot, Dispatcher, types, enums, F, filters
from aiogram.filters import or_f, and_f
from aiogram.types import User, BotCommand
from pydantic_settings import BaseSettings

from kibernikto.interactors import OpenAiExecutorConfig
from kibernikto.interactors.tools import Toolbox
from kibernikto.utils.text import split_text_by_sentences
from ._executor_corral import init as init_ai_bot_corral, get_ai_executor, kill as kill_animals
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from .telegram_bot import TelegramBot


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

        if TELEGRAM_SETTINGS.TG_SAY_HI and TELEGRAM_SETTINGS.TG_MASTER_ID:
            master_id = TELEGRAM_SETTINGS.TG_MASTER_ID
            await send_random_sticker(chat_id=master_id)
            bot: TelegramBot = get_ai_executor(master_id)
            hi_message = await bot.heed_and_reply("Поприветствуй своего хозяина!",
                                                  save_to_history=False)
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


@dp.message(and_f(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/')))
async def private_message(message: types.Message):
    user_id = message.from_user.id

    if TELEGRAM_SETTINGS.TG_MASTER_IDS and user_id not in TELEGRAM_SETTINGS.TG_MASTER_IDS:
        negative_reply_text = f"Я не отвечаю на вопросы в личных беседах с незакомыми людьми (если это конечно не один из моиз Повелителей " \
                              f"снизошёл до меня). Я передам ваше соообщение мастеру."
        await tg_bot.send_message(user_id,
                                  negative_reply_text)
        await tg_bot.send_message(TELEGRAM_SETTINGS.TG_MASTER_IDS[0],
                                  f"{message.from_user.username}: {message.md_text}")

    # TODO: plugins should be reworked and combined with preprocessor
    user_text = await preprocessor.process_tg_message(message, tg_bot=tg_bot)
    if user_text is None:
        return None  # do not reply
    user_ai = get_ai_executor(user_id)

    await tg_bot.send_chat_action(message.chat.id, 'typing')
    reply_text = await user_ai.heed_and_reply(message=user_text)

    if reply_text is None:
        reply_text = "Ok!"

    chunks = split_text_by_sentences(reply_text, TELEGRAM_SETTINGS.TG_MAX_MESSAGE_LENGTH)
    for chunk in chunks:
        await message.reply(text=chunk)


@dp.message(or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP))
async def group_message(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if TELEGRAM_SETTINGS.TG_FRIEND_GROUP_IDS and chat_id not in TELEGRAM_SETTINGS.TG_FRIEND_GROUP_IDS:
        negative_reply_text = (f"Я не общаюсь в беседах, в которых мне не велено участвовать"
                               f" (если это конечно не один из моих Повелителей"
                               f" снизошёл до меня). Я передам ваше соообщение кому-нибудь.")
        await tg_bot.send_message(user_id,
                                  negative_reply_text)
        await tg_bot.send_message(TELEGRAM_SETTINGS.TG_MASTER_IDS[0],
                                  f"{message.from_user.username}: {message.md_text}")

    user_text = await preprocessor.process_tg_message(message, tg_bot=tg_bot)
    if user_text is None:
        return None  # do not reply
    group_ai = get_ai_executor(chat_id)

    if is_reply(message) or group_ai.should_react(message.md_text):
        await tg_bot.send_chat_action(message.chat.id, 'typing')
        reply_text = await group_ai.heed_and_reply(message=user_text)

        chunks = split_text_by_sentences(reply_text, TELEGRAM_SETTINGS.TG_MAX_MESSAGE_LENGTH)
        for chunk in chunks:
            await message.reply(text=chunk)


def is_reply(message: types.Message):
    if message.reply_to_message and message.reply_to_message.from_user.id == tg_bot.id:
        return True
