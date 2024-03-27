import logging
from collections import deque
from enum import Enum
from typing import List

from openai import AsyncOpenAI
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from pydantic import BaseModel

from kibernikto.bots.ai_settings import AI_SETTINGS
from kibernikto.plugins import KiberniktoPlugin


class OpenAiExecutorConfig(BaseModel):
    name: str = "Киберникто"
    model: str = AI_SETTINGS.OPENAI_API_MODEL
    url: str = AI_SETTINGS.OPENAI_BASE_URL
    key: str = AI_SETTINGS.OPENAI_API_KEY
    temperature: float = AI_SETTINGS.OPENAI_TEMPERATURE
    max_tokens: int = AI_SETTINGS.OPENAI_MAX_TOKENS
    max_messages: int = AI_SETTINGS.OPENAI_MAX_MESSAGES
    who_am_i: str = AI_SETTINGS.OPENAI_WHO_AM_I
    reset_call: str = AI_SETTINGS.OPENAI_RESET_CALL
    master_call: str = "Величайший Кибеникто!"
    summarize_request: str | None = AI_SETTINGS.OPENAI_SUMMARY
    reaction_calls: list = ('никто', 'хонда', 'урод')


DEFAULT_CONFIG = OpenAiExecutorConfig()


class OpenAIRoles(str, Enum):
    system = 'system',
    user = 'user',
    assistant = 'assistant'


class OpenAIExecutor:
    MAX_WORD_COUNT = 3000
    """
    Basic Entity on the OpenAI library level.
    Sends requests and receives responses. Can store chat summary.
    Can process group chats at some point.
    """

    def __init__(self,
                 bored_after=0,
                 config=DEFAULT_CONFIG):
        self.max_messages = config.max_messages
        self.bored_after = bored_after
        self.master_call = config.master_call
        self.reset_call = config.reset_call
        self.summarize = config.summarize_request is not None

        self.client = AsyncOpenAI(base_url=config.url, api_key=config.key)

        self.model = config.model
        self.full_config = config

        # user messages preprocessing entities to go here
        self.plugins: List[KiberniktoPlugin] = []
        if self.max_messages < 2:
            self.max_messages = 2  # hahaha

        # default configuration. TODO: rework
        self._reset()

    @property
    def token_overflow(self):
        """
        if we exceeded max prompt tokens
        :return:
        """
        total_word_count = sum(
            len(obj["content"].split()) for obj in self.messages if obj["role"] != OpenAIRoles.system.value)
        return total_word_count > self.MAX_WORD_COUNT

    def should_react(self, message_text):
        """
        outer scope method to be used to understand if this instance should process the message
        :param message_text:
        :return:
        """
        return self.full_config.master_call in message_text or any(
            word in message_text.lower() for word in self.full_config.reaction_calls) or (
                self.full_config.name in message_text)

    async def heed(self, message, author=None):
        """
        Save message to history, but do not call OpenAI yet.
        :param message: recieved message
        :param author: outer chat message author
        :return:
        """
        self.reset_if_usercall(message)
        if len(message) > 200:
            return
        if author:
            this_message = dict(role=OpenAIRoles.user.value, content=f"{author}: {message}")
        else:
            this_message = dict(OpenAIRoles.user.value, f"{message}")
        await self._aware_overflow()
        self.messages.put(this_message)

    async def single_request(self, message, model=None):
        this_message = dict(content=f"{message}", role=OpenAIRoles.user.value)

        completion: ChatCompletion = await self.client.chat.completions.create(
            model=self.model if not model else model,
            messages=[this_message],
            max_tokens=self.full_config.max_tokens,
            temperature=self.full_config.temperature
        )
        response_message: ChatCompletionMessage = completion.choices[0].message

        return response_message

    async def heed_and_reply(self, message, author=NOT_GIVEN, save_to_history=True):
        """
        Sends message to OpenAI and receives response. Can preprocess user message and work before actual API call.
        :param message: received message
        :param author: outer chat message author. can be more or less understood by chat gpt.
        :param save_to_history: if to save
        :return: the text of OpenAI response
        """
        user_message = message
        self.reset_if_usercall(user_message)
        plugins_result, continue_execution = await self._run_plugins_for_message(user_message)
        if plugins_result is not None:
            if continue_execution is True:
                user_message = plugins_result
            else:
                return plugins_result

        this_message = dict(content=f"{user_message}", role=OpenAIRoles.user.value)

        await self._aware_overflow()

        prompt = [self.about_me] + list(self.messages) + [this_message]

        logging.debug(f"sending {prompt}")

        client: AsyncOpenAI = self.client

        completion: ChatCompletion = await client.chat.completions.create(
            model=self.model,
            messages=prompt,
            max_tokens=AI_SETTINGS.OPENAI_MAX_TOKENS,
            temperature=AI_SETTINGS.OPENAI_TEMPERATURE,
            user=author
        )
        response_message: ChatCompletionMessage = completion.choices[0].message

        if save_to_history:
            self.messages.append(this_message)
            self.messages.append(dict(role=response_message.role, content=response_message.content))

        return response_message.content

    def reset_if_usercall(self, message):
        if self.reset_call in message:
            self._reset()

    def _reset(self):
        # never gets full
        self.messages = deque(maxlen=self.max_messages)

        wai = self.full_config.who_am_i.format(self.full_config.name)
        self.about_me = dict(role=OpenAIRoles.system.value, content=wai)

        # self.messages.append(self.about_me)

    async def needs_attention(self, message):
        """checks if the reaction needed for the given messages"""
        return self.should_react(message)

    async def _run_plugins_for_message(self, message_text):
        plugins_result = None
        for plugin in self.plugins:
            plugin_result = await plugin.run_for_message(message_text)
            if plugin_result is not None:
                if not plugin.post_process_reply:
                    if plugin.store_reply:
                        self.messages.append(dict(content=f"{message_text}", role=OpenAIRoles.user.value))
                        self.messages.append(dict(role=OpenAIRoles.assistant.value, content=plugin_result))
                    return plugin_result, False
                else:
                    plugins_result = plugin_result
        return plugins_result, True

    async def _get_summary(self):
        """
        Performs OpenAPI call to summarize previous messages. Does not put about_me message, that can be a problem.
        :return: summary for current messages
        """
        logging.info(f"getting summary for {len(self.messages)} messages")
        response: ChatCompletion = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": self.full_config.summarize_request}] + list(self.messages),
            max_tokens=self.full_config.max_tokens,
            temperature=self.full_config.temperature,
        )
        response_text = response.choices[0].message.content.strip()
        logging.info(response_text)
        return response_text

    @property
    def token_overflow(self):
        """
        if we exceeded max word tokens
        :return:
        """
        total_word_count = sum(
            len(obj["content"].split()) for obj in self.messages if
            obj["role"] not in [OpenAIRoles.system.value] and obj["content"] is not None)
        return total_word_count > self.MAX_WORD_COUNT or len(self.messages) > self.max_messages

    async def _aware_overflow(self):
        """
        Checking if additional actions like cutting the message stack or summarization needed.
        We use words not tokens here, so all numbers are very approximate
        """
        if not self.summarize:
            while self.token_overflow:
                system_message = self.messages.popleft()
                for i in range(int(len(self.messages) / 3)):
                    self.messages.popleft()
                self.messages.appendleft(system_message)

        else:
            # summarizing previous discussion if needed
            if self.token_overflow:
                summary_text = await self._get_summary()
                summary = dict(role=OpenAIRoles.system.value, content=summary_text)
                self._reset()
                self.messages.append(summary)
