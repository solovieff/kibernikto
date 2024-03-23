import asyncio
import logging
import os
import random
import sys
import traceback
from random import choice
from typing import List, BinaryIO
from aiogram import Bot, Dispatcher, types, enums, F
from aiogram.types import User
from pydantic_settings import BaseSettings

from telegram.telegram_bot import TelegramBot
from kibernikto.interactors import OpenAiExecutorConfig

from kibernikto import constants
from kibernikto.utils.text import split_text_by_sentences, split_text_into_chunks_by_sentences
from kibernikto.plugins import KiberniktoPlugin
from kibernikto.utils.image import publish_image_file


class TelegramSettings(BaseSettings):
    TG_BOT_KEY: str
    TG_MASTER_ID: str
    TG_FRIEND_GROUP_ID: str
    TG_MAX_MESSAGE_LENGTH: int = 4096
    TG_CHUNK_SENTENCES: int = 5
    TG_REACTION_CALLS: list = ('honda', 'киберникто')
    TG_SAY_HI: bool = False
    TG_STICKER_LIST: list(str) = ()


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
    tg_bot = Bot(token=TelegramSettings.TG_BOT_KEY)
    dp.run_polling(tg_bot, skip_updates=True)


async def on_startup(bot: Bot):
    try:
        global bot_me
        global FRIEND_GROUP_BOT
        global PRIVATE_BOT

        executor_config = OpenAiExecutorConfig(name=bot_me.first_name,
                                               reaction_calls=TelegramSettings.TG_REACTION_CALLS)

        if bot_me is None:
            bot_me = await bot.get_me()
            bot_cfg = {
                "config": executor_config,
                "master_id": TelegramSettings.TG_MASTER_ID,
                "username": bot_me.username
            }
            FRIEND_GROUP_BOT: TelegramBot = smart_bot_class(**bot_cfg)
            PRIVATE_BOT: TelegramBot = smart_bot_class(**bot_cfg)

            # Initialize message processing plugins
            _apply_plugins([FRIEND_GROUP_BOT, PRIVATE_BOT])
            FRIEND_GROUP_BOT.full_config.reaction_calls.append(bot_me.username)
            FRIEND_GROUP_BOT.full_config.reaction_calls.append(bot_me.first_name)

            if TelegramSettings.TG_SAY_HI:
                await send_random_sticker(chat_id=TelegramSettings.TG_FRIEND_GROUP_ID)
                hi_message = await FRIEND_GROUP_BOT.heed_and_reply("Поприветствуй участников чата в двух предложениях!",
                                                                   save_to_history=False)
                await tg_bot.send_message(chat_id=TelegramSettings.TG_FRIEND_GROUP_ID, text=hi_message)
    except Exception as e:
        logging.error(f"failed to send hello message! {str(e)}")
        if FRIEND_GROUP_BOT.client is not None:
            await FRIEND_GROUP_BOT.client.close()
        if PRIVATE_BOT.client is not None:
            await PRIVATE_BOT.client.close()

        await dp.stop_polling()
        exit(os.EX_CONFIG)


async def send_random_sticker(chat_id):
    sticker_id = choice(TelegramSettings.TG_STICKER_LIST)

    # say hi to everyone
    await tg_bot.send_sticker(
        sticker=sticker_id,
        chat_id=chat_id)


@dp.message(F.chat.type == enums.ChatType.PRIVATE)
async def private_message(message: types.Message):
    if not PRIVATE_BOT.check_master(message.from_user.id, message.md_text):
        reply_text = f"Я не отвечаю на вопросы в личных беседах с незакомыми людьми (если это конечно не мой Господин " \
                     f"Создатель снизошёл до меня). Я передам ваше соообщение мастеру."
        await tg_bot.send_message(TelegramSettings.TG_MASTER_ID, f"{message.from_user.id}: {message.md_text}")
    else:
        await tg_bot.send_chat_action(message.chat.id, 'typing')
        user_text = await _get_message_text(message)
        await tg_bot.send_chat_action(message.chat.id, 'typing')
        reply_text = await PRIVATE_BOT.heed_and_reply(message=user_text)
    chunks = split_text_by_sentences(reply_text, TelegramSettings.TG_MAX_MESSAGE_LENGTH)
    for chunk in chunks:
        await message.reply(text=chunk)


@dp.message(F.chat.id == TelegramSettings.TG_FRIEND_GROUP_ID)
async def group_message(message: types.Message):
    if is_reply(message) or FRIEND_GROUP_BOT.should_react(message.text):
        await tg_bot.send_chat_action(message.chat.id, 'typing')
        user_text = await _get_message_text(message)
        logging.getLogger().info(f"group_message: from {message.from_user.full_name} in {message.chat.title} processed")

        await tg_bot.send_chat_action(message.chat.id, 'typing')
        # not using author not to send usernames to openai :)
        reply_text = await FRIEND_GROUP_BOT.heed_and_reply(user_text)  # author=message.from_user.full_name
        await asyncio.sleep(random.uniform(0, 2))
        chunks = split_text_into_chunks_by_sentences(reply_text, sentences_per_chunk=constants.TG_CHUNK_SENTENCES)
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

    for plugin_class in KiberniktoPlugin.__subclasses__():
        if plugin_class.applicable():
            try:
                plugin_instance = plugin_class()
                apply_plugin(plugin_instance)
            except Exception as plugin_error:
                logging.error(str(plugin_error))
                traceback.print_exc(file=sys.stdout)


async def _get_message_text(message: types.Message):
    user_text = message.md_text
    if message.content_type == enums.ContentType.PHOTO and message.photo:
        photo = message.photo[-1]
        file = await tg_bot.get_file(photo.file_id)
        file_path = file.file_path
        photo_file: BinaryIO = await tg_bot.download_file(file_path)
        # file_path = photo_file.file_path
        url = await publish_image_file(photo_file, photo.file_unique_id)
        logging.info(f"published image: {url}")

        user_text = f"{user_text} {url}"
    elif message.content_type == enums.ContentType.TEXT and message.text:
        return message.text
    return user_text
