import asyncio
import logging

from openai import AsyncOpenAI, PermissionDeniedError
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion, ChatCompletionMessage

from kibernikto import constants
from kibernikto.interactors import BaseTextConfig, InteractorOpenAI
from kibernikto.bots.cybernoone.prompt_preqs import MAIN_VERBAGE
import openai

from kibernikto.plugins import KiberniktoPluginException
from kibernikto.utils.text import remove_text_in_brackets_and_parentheses


class Vertihvostka(InteractorOpenAI):

    def __init__(self, max_messages=10, master_id=None, name="Вертихвостка", username="vertihvostka_bot",
                 who_am_i=MAIN_VERBAGE['who_am_i'],
                 reaction_calls=['verti', 'привет', 'хонда']):
        """

        :param max_messages: message history length
        :param master_id: telegram id of the master user
        :param name: current bot name
        :param who_am_i: default avatar prompt
        :param reaction_calls: words that trigger a reaction
        """
        pp = BaseTextConfig(who_am_i=who_am_i,
                            reaction_calls=reaction_calls, my_name=name)
        self.master_id = master_id
        self.name = name
        self.username = username
        super().__init__(model=constants.OPENAI_API_MODEL, max_messages=max_messages, default_config=pp)

        if constants.REDACTOR_OPENAI_API_KEY:
            self.redact_client = self.client = AsyncOpenAI(base_url=constants.REDACTOR_OPENAI_BASE_URL,
                                                           api_key=constants.REDACTOR_OPENAI_API_KEY)
        else:
            self.redact_client = None

    async def heed_and_reply(self, message, author=NOT_GIVEN, save_to_history=True):
        try:
            try:
                reply = await super().heed_and_reply(message, author, save_to_history=save_to_history)
                logging.info(reply)
            except PermissionDeniedError as pde:
                print(f"Я не знаю что сказать! {str(pde)}")
                await asyncio.sleep(1)
                reply = None

            if self.redact_client:
                if not reply:
                    reply = await self.redact_message(message, pure=True)
                else:
                    reply = await self.redact_message(reply)
                logging.info(reply)
            return reply
        except KiberniktoPluginException as e:
            return f" {e.plugin_name} не сработала!\n\n {str(e)}"
        except Exception as e:
            print(f"Я не знаю что сказать! {str(e)}")
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
                content=constants.REDACTOR_OPENAI_MESSAGE.format(message=message),
                role="user")
        else:
            user_message = dict(
                content=message,
                role="user")
        system_message = dict(content=f"{constants.REDACTOR_OPENAI_WHO_AM_I}", role="system")

        completion: ChatCompletion = await self.redact_client.chat.completions.create(
            model=constants.REDACTOR_OPENAI_API_MODEL,
            messages=[system_message, user_message],
            max_tokens=constants.OPENAI_MAX_TOKENS + 100,
            temperature=constants.OPENAI_TEMPERATURE
        )
        redacted_result = completion.choices[0].message.content
        return remove_text_in_brackets_and_parentheses(redacted_result)
