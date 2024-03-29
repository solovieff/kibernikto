import asyncio
import logging
import os
import random
import sys
import traceback
from random import choice
from typing import List

from aiogram import Bot, Dispatcher, types, enums, F
from aiogram.types import User
from pydantic_settings import BaseSettings

from kibernikto.interactors import OpenAiExecutorConfig
from kibernikto.plugins import KiberniktoPlugin
from kibernikto.utils.environment import print_plugin_banner, print_plugin_off
from kibernikto.utils.text import split_text_by_sentences, split_text_into_chunks_by_sentences
from ._message_preprocessors import get_message_text
from .telegram_bot import TelegramBot


class TelegramSettings(BaseSettings):
    TG_BOT_KEY: str
    TG_MASTER_ID: int
    TG_FRIEND_GROUP_ID: int
    TG_MAX_MESSAGE_LENGTH: int = 4096
    TG_CHUNK_SENTENCES: int = 7
    TG_REACTION_CALLS: List[str] = ['honda', 'киберникто']
    TG_SAY_HI: bool = False
    TG_STICKER_LIST: List[str] = ()


TELEGRAM_SETTINGS = TelegramSettings()

smart_bot_class = None

# Telegram bot
tg_bot: Bot = None
bot_me: User = None
dp = Dispatcher()

# Open AI bot instances.
# TODO: upper level class to create
FRIEND_GROUP_BOT: TelegramBot | None = None
PRIVATE_BOT: TelegramBot | None = None

MAX_TG_MESSAGE_LEN = 4096

commands = {}


def start(bot_class):
    """
    runs the executor polling the dispatcher for incoming messages

    :param bot_class: the bot class to use
    :return:
    """
    global smart_bot_class
    global tg_bot
    smart_bot_class = bot_class
    dp.startup.register(on_startup)
    tg_bot = Bot(token=TELEGRAM_SETTINGS.TG_BOT_KEY)
    dp.run_polling(tg_bot, skip_updates=True)


async def on_startup(bot: Bot):
    try:
        global bot_me
        global FRIEND_GROUP_BOT
        global PRIVATE_BOT

        if bot_me is None:
            bot_me = await bot.get_me()

        executor_config = OpenAiExecutorConfig(name=bot_me.first_name,
                                               reaction_calls=TELEGRAM_SETTINGS.TG_REACTION_CALLS)

        bot_cfg = {
            "config": executor_config,
            "master_id": TELEGRAM_SETTINGS.TG_MASTER_ID,
            "username": bot_me.username
        }
        FRIEND_GROUP_BOT = smart_bot_class(**bot_cfg)
        PRIVATE_BOT = smart_bot_class(**bot_cfg)

        # Initialize message processing plugins
        try:
            _apply_plugins([FRIEND_GROUP_BOT, PRIVATE_BOT])
        except Exception as plugin_error:
            logging.error(f"FAILED TO LOAD PLUGINS {plugin_error}")
            traceback.print_exc(file=sys.stdout)
        FRIEND_GROUP_BOT.full_config.reaction_calls.append(bot_me.username)
        FRIEND_GROUP_BOT.full_config.reaction_calls.append(bot_me.first_name)

        if TELEGRAM_SETTINGS.TG_SAY_HI:
            await send_random_sticker(chat_id=TELEGRAM_SETTINGS.TG_FRIEND_GROUP_ID)
            hi_message = await FRIEND_GROUP_BOT.heed_and_reply("Поприветствуй участников чата в двух предложениях!",
                                                               save_to_history=False)
            await tg_bot.send_message(chat_id=TELEGRAM_SETTINGS.TG_FRIEND_GROUP_ID, text=hi_message)
    except Exception as e:
        logging.error(f"failed to send hello message! \n{str(e)}")
        if FRIEND_GROUP_BOT.client is not None:
            await FRIEND_GROUP_BOT.client.close()
        if PRIVATE_BOT.client is not None:
            await PRIVATE_BOT.client.close()

        await dp.stop_polling()
        exit(os.EX_CONFIG)


async def send_random_sticker(chat_id):
    sticker_id = choice(TELEGRAM_SETTINGS.TG_STICKER_LIST)

    # say hi to everyone
    await tg_bot.send_sticker(
        sticker=sticker_id,
        chat_id=chat_id)


@dp.message(F.chat.type == enums.ChatType.PRIVATE)
async def private_message(message: types.Message):
    if not PRIVATE_BOT.check_master(message.from_user.id, message.md_text):
        reply_text = f"Я не отвечаю на вопросы в личных беседах с незакомыми людьми (если это конечно не мой Господин " \
                     f"Создатель снизошёл до меня). Я передам ваше соообщение мастеру."
        await tg_bot.send_message(TELEGRAM_SETTINGS.TG_MASTER_ID, f"{message.from_user.username}: {message.md_text}")
    else:
        await tg_bot.send_chat_action(message.chat.id, 'typing')
        user_text = await get_message_text(message, tg_bot)
        await tg_bot.send_chat_action(message.chat.id, 'typing')
        reply_text = await PRIVATE_BOT.heed_and_reply(message=user_text)
    chunks = split_text_by_sentences(reply_text, TELEGRAM_SETTINGS.TG_MAX_MESSAGE_LENGTH)
    for chunk in chunks:
        await message.reply(text=chunk)


@dp.message(F.chat.id == TELEGRAM_SETTINGS.TG_FRIEND_GROUP_ID)
async def group_message(message: types.Message):
    if is_reply(message) or FRIEND_GROUP_BOT.should_react(message.text):
        await tg_bot.send_chat_action(message.chat.id, 'typing')
        user_text = await get_message_text(message, tg_bot)
        logging.getLogger().info(f"group_message: from {message.from_user.full_name} in {message.chat.title} processed")

        await tg_bot.send_chat_action(message.chat.id, 'typing')
        # not using author not to send usernames to openai :)
        reply_text = await FRIEND_GROUP_BOT.heed_and_reply(user_text)  # author=message.from_user.full_name
        await asyncio.sleep(random.uniform(0, 2))
        chunks = split_text_into_chunks_by_sentences(reply_text,
                                                     sentences_per_chunk=TELEGRAM_SETTINGS.TG_CHUNK_SENTENCES)
        for chunk in chunks:
            await tg_bot.send_chat_action(message.chat.id, 'typing')
            await asyncio.sleep(random.uniform(0.5, 3))
            await message.reply(text=chunk)

        if random.random() < 0.1:
            await send_random_sticker(chat_id=message.chat.id)
    else:
        pass
        # for now we just ignore all non-related messages, even not putting them into history
        # await FRIEND_GROUP_BOT.heed(message=message.text, author=message.from_user.full_name)


def is_reply(message: types.Message):
    if message.reply_to_message and message.reply_to_message.from_user.id == tg_bot.id:
        return True


def _apply_plugins(bots: List[TelegramBot]):
    def apply_plugin(plugin):
        for bot in bots:
            bot.plugins.append(plugin)
        print_plugin_banner(plugin)

    plugin_classes = KiberniktoPlugin.__subclasses__()
    plugin_classes.sort(key=lambda x: x.index)

    for plugin_class in plugin_classes:
        if plugin_class.applicable():
            try:
                plugin_instance = plugin_class()
                apply_plugin(plugin_instance)
            except Exception as plugin_error:
                logging.error(str(plugin_error))
                traceback.print_exc(file=sys.stdout)
                logging.error("PLUGINS WERE NOT LOADED!")
        else:
            print_plugin_off(plugin_class)
