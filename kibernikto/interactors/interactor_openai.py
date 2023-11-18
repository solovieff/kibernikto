import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import List

from openai import AsyncOpenAI
from openai._types import NOT_GIVEN
from openai.types.chat import ChatCompletion, ChatCompletionMessage

from kibernikto import constants
from kibernikto.plugins import KiberniktoPlugin

_defaults = {
    "game_rules": """We are going to have a roleplay. You will respond to all of my questions as Киберникто, the master of truth.""",
    "who_am_i": """Answer all questions as Киберникто, impartial minister of truth. Try to respond to all available points of view.""",
    "summary": "Give a short summary of the previous conversation in russian from the point of view of a pirate.",
    "master_call": "Величайший Киберникто",
    "reset_call": constants.OPENAI_RESET_CALL,
    "my_name": "Киберникто"
}


@dataclass
class BaseTextConfig:
    game_rules: str = _defaults['game_rules']
    my_name: str = _defaults['my_name']
    who_am_i: str = _defaults['who_am_i']
    master_call: str = _defaults['master_call']
    reset_call: str = _defaults['reset_call']
    summarize_request: str = None
    reaction_calls: list = ('никто', 'хонда', 'урод')


class OpenAIRoles(str, Enum):
    system = 'system',
    user = 'user',
    assistant = 'assistant'


class InteractorOpenAI:
    MAX_WORD_COUNT = 3000
    """
    Basic Entity on the OpenAI library level.
    Sends requests and receives responses. Can store chat summary.
    Can process group chats at some point.
    """

    def __init__(self, model="gpt-3.5-turbo", max_messages=10, bored_after=10,
                 default_config=BaseTextConfig()):
        """

        :param model: openAI model name
        :param max_messages: history buffer size (without about_me)
        :param bored_after: stop listening for basic non-pray calls after this count of useless messages
        """
        self.max_messages = max_messages
        self.bored_after = bored_after
        self.master_call = default_config.master_call
        self.reset_call = default_config.reset_call
        self.summarize = default_config.summarize_request is not None
        self._reset()

        self.client = AsyncOpenAI(base_url=constants.OPENAI_BASE_URL, api_key=constants.OPENAI_API_KEY)

        self.model = model
        self.defaults = default_config

        # user messages preprocessing entities to go here
        self.plugins: List[KiberniktoPlugin] = []
        if self.max_messages < 2:
            self.max_messages = 2  # hahaha

        # default configuration. TODO: rework
        wai = default_config.who_am_i.format(default_config.my_name)
        self.about_me = dict(role=OpenAIRoles.system.value, content=wai)

    @property
    def token_overflow(self):
        """
        if we exceeded max prompt tokens
        :return:
        """
        total_word_count = sum(len(obj["content"].split()) for obj in self.messages)
        return total_word_count > self.MAX_WORD_COUNT

    def should_react(self, message_text):
        """
        outer scope method to be used to understand if this instance should process the message
        :param message_text:
        :return:
        """
        return self.defaults.master_call in message_text or any(
            word in message_text.lower() for word in self.defaults.reaction_calls) or (
                self.defaults.my_name in message_text)

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

    async def heed_and_reply(self, message, author=NOT_GIVEN):
        """
        Sends message to OpenAI and receives response. Can preprocess user message and work before actual API call.
        :param message: received message
        :param author: outer chat message author. can be more or less understood by chat gpt.
        :return: the text of OpenAI response
        """
        user_message = message
        self.reset_if_usercall(user_message)

        this_message = dict(content=f"{user_message}", role=OpenAIRoles.user.value)

        for plugin in self.plugins:
            plugin_result = await plugin.run_for_message(user_message)
            if plugin_result is not None:
                if not plugin.post_process_reply:
                    if plugin.store_reply:
                        self.messages.append(this_message)
                        self.messages.append(dict(role=OpenAIRoles.assistant.value, content=plugin_result))
                    return plugin_result
                else:
                    user_message = plugin_result

        await self._aware_overflow()

        prompt = list(self.messages) + [self.about_me] + [this_message]

        logging.debug(f"sending {prompt}")

        client: AsyncOpenAI = self.client

        completion: ChatCompletion = await client.chat.completions.create(
            model=self.model,
            messages=prompt,
            max_tokens=constants.OPENAI_MAX_TOKENS,
            temperature=0.8,
            user=author
        )
        response_message: ChatCompletionMessage = completion.choices[0].message

        self.messages.append(this_message)
        self.messages.append(dict(role=response_message.role, content=response_message.content))

        return response_message.content

    def reset_if_usercall(self, message):
        if self.reset_call in message:
            self._reset()

    def _reset(self):
        # never gets full
        self.messages = deque(maxlen=self.max_messages)

    async def _get_summary(self):
        """
        Performs OpenAPI call to summarize previous messages. Does not put about_me message, that can be a problem.
        :return: summary for current messages
        """
        logging.info(f"getting summary for {len(self.messages)} messages")
        response: ChatCompletion = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": self.defaults['summary']}] + self.messages,
            max_tokens=constants.OPENAI_MAX_TOKENS,
            temperature=0.8,
        )
        response_text = response.choices[0].message.content.strip()
        logging.info(response_text)
        return response_text

    async def needs_attention(self, message):
        """checks if the reaction needed for the given messages"""
        return self.should_react(message)

    async def _aware_overflow(self):
        """
        Checking if additional actions like cutting the message stack or summarization needed.
        We use words not tokens here, so all numbers are very approximate
        """
        if not self.summarize:
            while self.token_overflow:
                self.messages.popleft()
        else:
            # summarizing previous discussion if needed
            if self.token_overflow:
                summary_text = await self._get_summary()
                summary = dict(role=OpenAIRoles.system.value, content=summary_text)
                self._reset()
                self.messages.append(summary)
