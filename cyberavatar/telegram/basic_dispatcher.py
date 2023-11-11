import asyncio
import logging
import os
import random
from random import choice

from aiogram import Bot, Dispatcher, types, enums, F

from cyberavatar import constants, utils as cyberutils
from cyberavatar.utils.text import split_text, MAX_MESSAGE_LENGTH

# Initialize tg_bot and dispatcher

smart_bot_class = None

# Telegram bot
tg_bot = None
bot_me = None
dp = Dispatcher()

# Open AI bot instances
FRIEND_GROUP_BOT = None
PRIVATE_BOT = None

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
    tg_bot = Bot(token=constants.TG_BOT_KEY)
    dp.run_polling(tg_bot, skip_updates=True)


async def on_startup(bot: Bot):
    try:
        global bot_me
        global FRIEND_GROUP_BOT
        global PRIVATE_BOT

        if bot_me is None:
            bot_me = await bot.get_me()
            FRIEND_GROUP_BOT = smart_bot_class(max_messages=constants.TG_BOT_MAX_HISTORY,
                                               master_id=constants.TG_MASTER_ID,
                                               name=bot_me.first_name,
                                               who_am_i=constants.OPENAI_WHO_AM_I,
                                               reaction_calls=constants.TG_REACTION_CALLS)
            PRIVATE_BOT = smart_bot_class(max_messages=constants.TG_BOT_MAX_HISTORY,
                                          master_id=constants.TG_MASTER_ID,
                                          name=bot_me.first_name,
                                          who_am_i=constants.OPENAI_WHO_AM_I,
                                          reaction_calls=constants.TG_REACTION_CALLS)

            # Initialize message processing filters
            if constants.SUMMARIZATION_KEY:
                PRIVATE_BOT.filters.append(cyberutils.youtube.get_transcript_if_video)
                FRIEND_GROUP_BOT.filters.append(cyberutils.youtube.get_transcript_if_video)

            FRIEND_GROUP_BOT.defaults.reaction_calls.append(bot_me.username)
            FRIEND_GROUP_BOT.defaults.reaction_calls.append(bot_me.first_name)

            await send_random_sticker(chat_id=constants.TG_FRIEND_GROUP_ID)
            hi_message = await FRIEND_GROUP_BOT.heed_and_reply("Поприветствуй участников чата!")
            await tg_bot.send_message(chat_id=constants.TG_FRIEND_GROUP_ID, text=hi_message)
    except Exception as e:
        logging.error("failed to send hello message!", e)
        dp.stop_polling()
        exit(os.EX_CONFIG)


async def send_random_sticker(chat_id):
    sticker_id = choice(constants.TG_STICKER_LIST)

    # say hi to everyone
    await tg_bot.send_sticker(
        sticker=sticker_id,
        chat_id=chat_id)


@dp.message(F.chat.type == enums.ChatType.PRIVATE)
async def private_message(message: types.Message):
    if not PRIVATE_BOT.check_master(message.from_user.id, message.text):
        reply_text = "Я не отвечаю на вопросы в личных беседах с незанкомыми людьми (если это конечно не мой Господин " \
                     "Создатель снизошёл до меня). Идите нахуй."
    else:
        reply_text = await PRIVATE_BOT.heed_and_reply(message=message.text)
    chunks = split_text(reply_text, MAX_MESSAGE_LENGTH)
    for chunk in chunks:
        await message.reply(text=chunk)


@dp.message(F.chat.id == constants.TG_FRIEND_GROUP_ID)
async def group_message(message: types.Message):
    logging.getLogger().info(f"group_message: from {message.from_user.full_name} in {message.chat.title} processed")
    if is_reply(message) or FRIEND_GROUP_BOT.should_react(message.text):
        await tg_bot.send_chat_action(message.chat.id, 'typing')
        reply_text = await FRIEND_GROUP_BOT.heed_and_reply(message.text)  # , author=message.from_user.full_name
        chunks = split_text(reply_text, MAX_MESSAGE_LENGTH)
        for chunk in chunks:
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
