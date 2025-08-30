import logging
import sys
import traceback
from contextlib import asynccontextmanager
from typing import Dict, Type

from aiogram.types import User, Chat
from pydantic import BaseModel

from kibernikto.interactors import OpenAiExecutorConfig
from kibernikto.telegram.telegram_bot import TelegramBot, KiberniktoChatInfo
from kibernikto.bots.telegram_agent import KiberniktoTelegramAgent


class AIBotConfig(BaseModel):
    config: OpenAiExecutorConfig
    master_id: int
    username: str


__BOTS: Dict[int | str, TelegramBot | KiberniktoTelegramAgent] = {}
__BOT_CLASS: Type[TelegramBot | KiberniktoTelegramAgent] = None
__EXECUTOR_CONFIG: AIBotConfig = None


def init(master_id: int, username: str, config: OpenAiExecutorConfig,
         smart_bot_class: Type[TelegramBot | KiberniktoTelegramAgent]):
    global __EXECUTOR_CONFIG
    global __BOT_CLASS
    """
    run the corral and set defaults

    :param master_id: master outer tg id
    :param username:
    :param config:
    :param smart_bot_class:
    :return: nothing
    """
    __BOT_CLASS = smart_bot_class
    __EXECUTOR_CONFIG = AIBotConfig(config=config, master_id=master_id, username=username)


async def kill(exact_ids=()):
    for key in __BOTS:
        bot = __BOTS[key]
        if exact_ids:
            if key in exact_ids and bot.restrict_client_instance is not True:
                await bot.client.close()
        else:
            # this will kill a global client. So it has to be restarted manually after this.
            await bot.client.close()


def get_ai_executor(key_id: int | str) -> TelegramBot:
    bot = __BOTS.get(key_id)
    return bot


@asynccontextmanager
async def get_temp_executor(key_id: int | str) -> TelegramBot:
    bot = _new_executor(key_id=key_id)
    try:
        yield bot
    finally:
        if bot and bot.restrict_client_instance is not True:
            await bot.client.close()


def executor_exists(key_id: int | str) -> bool:
    return key_id in __BOTS


def get_ai_executor_full(chat: Chat, user: User = None, hide_errors=True) -> TelegramBot:
    chat_key = chat.id
    bot = __BOTS.get(chat_key)

    if not bot:
        chat_info = KiberniktoChatInfo(chat, user)
        bot = _new_executor(key_id=chat_key, chat_info=chat_info)
        if hasattr(bot, 'hide_errors'):
            bot.hide_errors = hide_errors
        __BOTS[chat_key] = bot
    return bot


def _new_executor(key_id: int | str, chat_info: KiberniktoChatInfo = None):
    """
    creates new ai bot executor connected to AI API
    :return:
    :rtype:
    """
    _configuration = __EXECUTOR_CONFIG.model_copy(deep=True)
    bot = __BOT_CLASS(username=_configuration.username,
                      config=_configuration.config,
                      key=key_id, chat_info=chat_info)
    if chat_info is not None:
        print(f'- new {__BOT_CLASS.__name__} ai executor was created for "{chat_info.full_name}" with key "{key_id}"')
    else:
        print(f'- new temp {__BOT_CLASS.__name__} ai executor was created')
    return bot
