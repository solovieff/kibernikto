import asyncio
import logging

from openai import AsyncOpenAI, PermissionDeniedError
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion

from kibernikto.interactors import OpenAiExecutorConfig
from kibernikto.plugins import KiberniktoPluginException
from kibernikto.telegram.telegram_bot import TelegramBot
from kibernikto.utils.text import remove_text_in_brackets_and_parentheses
from kibernikto.utils.environment import feature_not_configured
from ..redactor_settings import REDACTOR_SETTINGS


class Vertihvostka(TelegramBot):
    """
    Can post-process ai replies using another model conf.
    Useful for adding style/mood or chaning the output text.
    """

    def __init__(self, master_id: str, username: str, config: OpenAiExecutorConfig):
        """
        :param master_id: telegram admin id
        :param username: telegram username
        :param config: ai bot config
        """
        if REDACTOR_SETTINGS.OPENAI_API_KEY is not None:
            self.redact_client = AsyncOpenAI(base_url=REDACTOR_SETTINGS.OPENAI_BASE_URL,
                                             api_key=REDACTOR_SETTINGS.OPENAI_API_KEY)
        else:
            feature_not_configured("redactor_ai")
            self.redact_client = None

        super().__init__(config=config, username=username, master_id=master_id)

    async def heed_and_reply(self, message, author=NOT_GIVEN, save_to_history=True):
        try:
            try:
                reply = await super().heed_and_reply(message, author, save_to_history=save_to_history)
                logging.info(reply)
            except PermissionDeniedError as pde:
                logging.warning(f"Что-то грубое и недопустимое! {str(pde)}")
                await asyncio.sleep(1)
                reply = None

            if not self.redact_client:
                if reply is None:
                    return "Что-то грубое и недопустимое в ваших словах!"
                else:
                    return reply

            if self.redact_client:
                if not reply:
                    logging.warning("sending the message right to redactor")
                    reply = await self.redact_message(message, pure=True)
                else:
                    reply = await self.redact_message(reply)
                logging.info(reply)
            # this should be processed better for sure
            return reply
        except KiberniktoPluginException as e:
            return f" {e.plugin_name} поломался!\n\n {str(e)}"
        except Exception as e:
            logging.error(f"Я не знаю что сказать! {str(e)}")
            return f"Я не знаю что сказать! Похоже я сломался!"

    def check_master(self, user_id, message):
        return self.master_call in message or user_id == self.master_id

    def should_react(self, message_text):
        if not message_text:
            return False
        parent_should = super().should_react(message_text)
        return parent_should or self.username in message_text

    async def redact_message(self, message, pure=False):
        if not pure:
            user_message = dict(
                content=REDACTOR_SETTINGS.MESSAGE.format(message=message),
                role="user")
        else:
            user_message = dict(
                content=message,
                role="user")
        if REDACTOR_SETTINGS.OPENAI_WHO_AM_I:
            system_message = dict(content=f"{REDACTOR_SETTINGS.OPENAI_WHO_AM_I}", role="system")
            red_prompt = [system_message, user_message]
        else:
            red_prompt = [user_message]

        completion: ChatCompletion = await self.redact_client.chat.completions.create(
            model=REDACTOR_SETTINGS.OPENAI_API_MODEL,
            messages=red_prompt,
            max_tokens=REDACTOR_SETTINGS.OPENAI_MAX_TOKENS,
            temperature=self.full_config.temperature + 0.3
        )
        redacted_result = completion.choices[0].message.content
        return remove_text_in_brackets_and_parentheses(redacted_result)
