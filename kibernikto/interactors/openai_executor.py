import logging
from collections import deque
from enum import Enum
from typing import List

from openai import AsyncOpenAI
from openai._types import NOT_GIVEN
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice

from pydantic import BaseModel

from kibernikto.bots.ai_settings import AI_SETTINGS
from kibernikto.interactors.tools import Toolbox
from kibernikto.plugins import KiberniktoPlugin
from kibernikto.utils import ai_tools


class OpenAiExecutorConfig(BaseModel):
    name: str = "Киберникто"
    model: str = AI_SETTINGS.OPENAI_API_MODEL
    url: str = AI_SETTINGS.OPENAI_BASE_URL
    key: str = AI_SETTINGS.OPENAI_API_KEY
    temperature: float = AI_SETTINGS.OPENAI_TEMPERATURE
    max_tokens: int = AI_SETTINGS.OPENAI_MAX_TOKENS
    input_price: float | None = AI_SETTINGS.OPENAI_INPUT_PRICE
    output_price: float | None = AI_SETTINGS.OPENAI_OUTPUT_PRICE
    max_messages: int = AI_SETTINGS.OPENAI_MAX_MESSAGES
    max_retries: int = AI_SETTINGS.OPENAI_MAX_RETRIES
    who_am_i: str = AI_SETTINGS.OPENAI_WHO_AM_I
    reset_call: str = AI_SETTINGS.OPENAI_RESET_CALL
    master_call: str = "Величайший Кибеникто!"
    summarize_request: str | None = AI_SETTINGS.OPENAI_SUMMARY
    max_words_before_summary: int = AI_SETTINGS.OPENAI_MAX_WORDS
    reaction_calls: list = ('никто', 'хонда', 'урод')
    tools: List[Toolbox] = []
    hide_errors: bool = False


DEFAULT_CONFIG = OpenAiExecutorConfig()


class OpenAIRoles(str, Enum):
    system = 'system',
    user = 'user',
    assistant = 'assistant'


class OpenAIExecutor:
    """
    Basic Entity on the OpenAI library level.
    Sends requests and receives responses. Can store chat summary.
    Can process group chats at some point.
    """

    def __init__(self,
                 bored_after=0,
                 config=DEFAULT_CONFIG, unique_id=NOT_GIVEN):
        if config.max_messages % 2 == 0:
            self.max_messages = config.max_messages
        else:
            self.max_messages = config.max_messages + 1

        self.bored_after = bored_after
        self.master_call = config.master_call
        self.reset_call = config.reset_call
        self.unique_id = unique_id
        self.summarize = config.max_words_before_summary != 0
        self.client = AsyncOpenAI(base_url=config.url, api_key=config.key, max_retries=DEFAULT_CONFIG.max_retries)

        self.model = config.model
        self.full_config = config

        # user string messages preprocessing entities to go here
        self.plugins: List[KiberniktoPlugin] = []

        # additional tools in Toolbox formats
        self.tools: List[Toolbox] = config.tools

        if self.max_messages < 2:
            self.max_messages = 2  # hahaha

        # default configuration. TODO: rework
        self._reset()

    @property
    def tools_definitions(self):
        if self.xml_tools:
            return []
        else:
            return [toolbox.definition for toolbox in self.tools]

    @property
    def xml_tools(self):
        return "claude" in self.model and 1 == 2

    def _get_tool_implementation(self, name):
        for x in self.tools:
            if x.function_name == name:
                return x.implementation

    def process_usage(self, usage: CompletionUsage) -> dict | None:
        """
        Calculates usage costs if possible
        :param usage:
        :return: usage dict updated with costs
        """
        logging.warning(f"usage is {usage}")
        if not usage:
            logging.debug("usage unknown!")
            return None

        usage_dict = usage.model_dump()
        usage_dict['completion_cost'] = 0
        usage_dict['prompt_cost'] = 0
        usage_dict['total_cost'] = 0

        if self.full_config.input_price and self.full_config.output_price:
            total = 0
            if usage.completion_tokens:
                completion_cost = usage.completion_tokens * self.full_config.output_price
                total += completion_cost
                usage_dict['completion_cost'] = completion_cost
            if usage.prompt_tokens:
                prompt_cost = usage.prompt_tokens * self.full_config.input_price
                total += prompt_cost
                usage_dict['prompt_cost'] = prompt_cost
            usage_dict['total_cost'] = total
        else:
            logging.warning("no OPENAI_INPUT_PRICE (input_price) and OPENAI_OUTPUT_PRICE (output_price) provided")
        logging.debug(f"process_usage: {usage_dict}")
        return usage_dict

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
            messages=[self.about_me, this_message],
            max_tokens=self.full_config.max_tokens,
            temperature=self.full_config.temperature
        )
        choice: Choice = completion.choices[0]
        usage_dict = self.process_usage(completion.usage)
        return choice, usage_dict

    async def _run_for_messages(self, full_prompt, author=NOT_GIVEN):
        tools_to_use = self.tools_definitions if self.tools_definitions else NOT_GIVEN

        completion: ChatCompletion = await self.client.chat.completions.create(
            model=self.model,
            messages=full_prompt,
            max_tokens=AI_SETTINGS.OPENAI_MAX_TOKENS,
            temperature=AI_SETTINGS.OPENAI_TEMPERATURE,
            user=author,
            tools=tools_to_use
        )
        choice: Choice = completion.choices[0]
        usage_dict = self.process_usage(completion.usage)
        return choice, usage_dict

    async def heed_and_reply(self, message: str, author=NOT_GIVEN, save_to_history=True):
        """
        Sends message to OpenAI and receives response. Can preprocess user message and work before actual API call.
        :param message: received message
        :param author: outer chat message author. can be more or less understood by chat gpt.
        :param save_to_history: if to save
        :return: the text of OpenAI response
        """
        user_message = message
        self.reset_if_usercall(user_message)
        plugins_result, continue_execution = await self._run_plugins_for_message(user_message, author)
        if plugins_result is not None:
            if continue_execution is True:
                user_message = plugins_result
            else:
                return plugins_result

        this_message = dict(content=f"{user_message}", role=OpenAIRoles.user.value)

        await self._aware_overflow()

        prompt = [self.get_cur_system_message()] + list(self.messages) + [this_message]

        logging.debug(f"sending {prompt}")

        choice, usage = await self._run_for_messages(prompt, author)
        response_message: ChatCompletionMessage = choice.message

        if ai_tools.is_function_call(choice=choice, xml=self.xml_tools):
            return await self.process_tool_calls(choice, user_message)

        if save_to_history:
            self.save_to_history(this_message, usage_dict=usage, author=author)
            self.save_to_history(dict(role=response_message.role, content=response_message.content),
                                 usage_dict=usage,
                                 author=author)

        return response_message.content

    def reset_if_usercall(self, message):
        if self.reset_call in message:
            self._reset()

    def get_cur_system_message(self):
        return self.about_me

    def save_to_history(self, this_message: dict, usage_dict: dict = None, author=NOT_GIVEN):
        self.messages.append(this_message)

    def _reset(self):
        # never gets full, +1 for system

        self.messages = deque(maxlen=self.max_messages)

        wai = self.full_config.who_am_i.format(self.full_config.name)

        self.about_me = dict(role=OpenAIRoles.system.value, content=f"{wai}")

    async def needs_attention(self, message):
        """checks if the reaction needed for the given message"""
        return self.should_react(message)

    async def process_tool_calls(self, choice: Choice, original_request_text: str, save_to_history=True):
        prompt = list(self.messages)
        if not choice.message.tool_calls:
            raise ValueError("No tools provided!")
        message_dict = None
        tool_call_messages = []
        for tool_call in choice.message.tool_calls:
            fn_name = tool_call.function.name
            function_impl = self._get_tool_implementation(fn_name)
            additional_params = {
                "key": self.unique_id
            }
            tool_call_result = await ai_tools.execute_tool_call_function(tool_call, function_impl=function_impl,
                                                                         additional_params=additional_params)
            message_dict = dict(content=f"{original_request_text}", role=OpenAIRoles.user.value)
            prompt.append(message_dict)
            tool_call_messages += ai_tools.get_tool_call_serving_messages(tool_call, tool_call_result,
                                                                          xml=self.xml_tools)

        choice, usage = await self._run_for_messages(full_prompt=prompt + tool_call_messages)
        response_message: ChatCompletionMessage = choice.message
        if save_to_history and message_dict:
            self.save_to_history(message_dict, usage_dict=usage)
            for tool_call_message in tool_call_messages:
                self.save_to_history(tool_call_message, usage_dict=usage)
        return response_message.content

    async def _run_plugins_for_message(self, message_text, author=NOT_GIVEN):
        plugins_result = None
        for plugin in self.plugins:
            plugin_result = await plugin.run_for_message(message_text)
            if plugin_result is not None:
                if not plugin.post_process_reply:
                    if plugin.store_reply:
                        self.save_to_history(dict(content=f"{message_text}", role=OpenAIRoles.user.value),
                                             author=author)
                        self.save_to_history(
                            dict(role=OpenAIRoles.assistant.value, content=plugin_result, author=author))
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
        sum_request = {"role": "user", "content": self.full_config.summarize_request}

        response: ChatCompletion = await self.client.chat.completions.create(
            model=self.model,
            messages=list(self.messages) + [sum_request],
            max_tokens=self.full_config.max_tokens,
            temperature=self.full_config.temperature,
        )
        response_text = response.choices[0].message.content.strip()
        usage_dict = self.process_usage(response.usage)
        logging.info(response_text)
        return response_text, usage_dict

    @property
    def word_overflow(self):
        """
        if we exceeded max word tokens
        :return:
        """
        total_word_count = sum(
            len(obj["content"].split()) for obj in list(self.messages) if
            obj["role"] not in [OpenAIRoles.system.value] and obj["content"] is not None)
        return ((
                        self.full_config.max_words_before_summary and total_word_count > self.full_config.max_words_before_summary) or
                len(self.messages) > self.max_messages)

    async def _aware_overflow(self):
        """
        Checking if additional actions like cutting the message stack or summarization needed.
        We use words not tokens here, so all numbers are very approximate
        """
        if self.word_overflow:
            if not self.full_config.summarize_request:
                self.messages.popleft()
                self.messages.popleft()
            else:
                # summarizing previous discussion if needed

                logging.warning("You speak too much! Performing summarization!")
                summary_text, usage_dict = await self._get_summary()
                summary = dict(role=OpenAIRoles.system.value,
                               content=f"just in case, summary of the previous dialogue, don't give it much thought: {summary_text}")
                self._reset()
                self.save_to_history(summary, usage_dict=usage_dict)
