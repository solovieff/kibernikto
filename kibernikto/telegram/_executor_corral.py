import logging
import sys
import traceback
from typing import Dict, Type, List

from openai._types import NOT_GIVEN

from kibernikto.plugins import KiberniktoPlugin

from kibernikto.utils.environment import print_plugin_banner, print_plugin_off
from pydantic import BaseModel

from .telegram_bot import TelegramBot
from kibernikto.interactors import OpenAiExecutorConfig


class AIBotConfig(BaseModel):
    config: OpenAiExecutorConfig
    master_id: int
    username: str


__BOTS: Dict[int, TelegramBot] = {}
__BOT_CLASS: Type[TelegramBot] = None
__EXECUTOR_CONFIG: AIBotConfig = None


def init(master_id: int, username: str, config: OpenAiExecutorConfig, smart_bot_class: Type[TelegramBot]):
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


async def kill():
    for key in __BOTS:
        bot = __BOTS[key]
        await bot.client.close()


def get_ai_executor(key_id: int):
    bot = __BOTS.get(key_id)

    if not bot:
        bot = _new_executor(str(key_id))
        _apply_plugins(bot)
        __BOTS[key_id] = bot
    return bot


def _apply_plugins(bot: TelegramBot):
    def apply_plugin(plugin: KiberniktoPlugin):
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


def _new_executor(key_id: str = NOT_GIVEN):
    """
    creates new ai bot executor connected to AI API
    :return:
    :rtype:
    """
    _configuration = __EXECUTOR_CONFIG.model_copy(deep=True)
    bot = __BOT_CLASS(username=_configuration.username,
                      master_id=_configuration.master_id,
                      config=_configuration.config,
                      key=key_id)
    return bot
