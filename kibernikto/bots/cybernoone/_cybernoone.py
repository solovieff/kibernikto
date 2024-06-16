import logging
import traceback

from openai import PermissionDeniedError
from openai._types import NOT_GIVEN

from kibernikto.telegram.telegram_bot import TelegramBot, KiberniktoChatInfo
from kibernikto.interactors import OpenAiExecutorConfig
import openai

from kibernikto.plugins import KiberniktoPluginException


class Kibernikto(TelegramBot):
    """
    Basic implementation of Telegram bot.
    """

    def __init__(self, master_id: str, username: str, config: OpenAiExecutorConfig, key=NOT_GIVEN,
                 chat_info: KiberniktoChatInfo = None):
        """
        :param master_id: telegram admin id
        :param username: telegram username
        :param config: ai bot config
        """
        self.key = key
        super().__init__(config=config, username=username, master_id=master_id, key=key, chat_info=chat_info)

    async def heed_and_reply(self, message, author=NOT_GIVEN, save_to_history=True):
        try:
            if self.username in message:
                message_to_send = message.replace(f"@{self.username}", '')
            else:
                message_to_send = message
            return await super().heed_and_reply(message_to_send, author, save_to_history=save_to_history)
        except KiberniktoPluginException as e:
            return f" {e.plugin_name} не сработал!\n\n {str(e)}"
        except PermissionDeniedError as pde:
            logging.warning(f"Что-то грубое и недопустимое! {str(pde)}")
            return "Что-то грубое и недопустимое в ваших словах!"
        except Exception as e:
            print(traceback.format_exc())
            return f"Я не справился! Горе мне! {str(e)}"

    # FIXME: not working properly
    async def ask_pure(self, prompt):
        response = await openai.ChatCompletion.acreate(
            model=self.model,
            messages=prompt,
            max_tokens=self.full_config.max_tokens,
            temperature=self.full_config.temperature,
        )
        response_text = response['choices'][0]['message']['content'].strip()
        print(response_text)
        return response_text
