import logging
import os
from collections import deque
from dataclasses import dataclass
from enum import Enum

import openai

from cyberavatar.constants import OPENAI_MAX_TOKENS, OPENAI_RESET_CALL

_defaults = {
    "game_rules": """We are going to have a roleplay. You will respond to all of my questions as Киберникто, the master of truth.""",
    "who_am_i": """Answer all questions as Киберникто, impartial minister of truth. Try to respond to all available points of view.""",
    "summary": "Give a short summary of the previous conversation in russian from the point of view of a pirate.",
    "master_call": "Величайший Киберникто",
    "reset_call": OPENAI_RESET_CALL,
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

        self.model = model
        self.defaults = default_config

        # user messages preprocessing entities to go here
        self.filters = []
        if self.max_messages < 2:
            self.max_messages = 2  # hahaha

        # default configuration. TODO: rework
        wai = default_config.who_am_i.format(default_config.my_name)
        self.about_me = {"role": OpenAIRoles.system.value, "content": wai}

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
            this_message = self._form_message(OpenAIRoles.user.value, f"{author}: {message}")
        else:
            this_message = self._form_message(OpenAIRoles.user.value, f"{message}")
        await self._aware_overflow()
        self.messages.put(this_message)

    async def heed_and_reply(self, message, author=None):
        """
        Sends message to OpenAI and receives response. Can preprocess user message and work before actual API call.
        :param message: received message
        :param author: outer chat message author. can be more or less understood by chat gpt.
        :return: the text of OpenAI response
        """
        for preprocessor in self.filters:
            filter_result = preprocessor(message)
            if filter_result is not None:
                return filter_result

        self.reset_if_usercall(message)

        if author:
            this_message = self._form_message(OpenAIRoles.user.value, f"{author}: {message}")
        else:
            this_message = self._form_message(OpenAIRoles.user.value, f"{message}")

        await self._aware_overflow()

        prompt = list(self.messages) + [self.about_me] + [this_message]

        logging.debug(f"sending {prompt}")

        response = await openai.ChatCompletion.acreate(
            model=self.model,
            messages=prompt,
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=0.8,
        )
        response_text = response['choices'][0]['message']['content'].strip()
        self.messages.append(this_message)
        response_message = self._form_message(OpenAIRoles.assistant.value, response_text)
        self.messages.append(response_message)
        return response_text

    def reset_if_usercall(self, message):
        if self.reset_call in message:
            self._reset()

    def _reset(self):
        # never gets full
        self.messages = deque(maxlen=self.max_messages)

    def _form_message(self, user, text):
        """

        :param user: OpenAIRoles
        :param text:
        :return:
        """
        return {"role": user, "content": text}

    async def _get_summary(self):
        """
        Performs OpenAPI call to summarize previous messages. Does not put about_me message, that can be a problem.
        :return: summary for current messages
        """
        logging.info(f"getting summary for {len(self.messages)} messages")
        response = await openai.ChatCompletion.acreate(
            model=self.model,
            messages=[{"role": "system", "content": self.defaults['summary']}] + self.messages,
            max_tokens=OPENAI_MAX_TOKENS / 2,
            temperature=0.7,
        )
        response_text = response['choices'][0]['message']['content'].strip()
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
                summary = self._form_message(OpenAIRoles.system, summary_text)
                self._reset()
                self.messages.append(summary)
