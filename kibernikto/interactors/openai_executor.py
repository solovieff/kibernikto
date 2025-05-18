import logging
import pprint
from collections import deque
from enum import Enum
from typing import List, Literal

from openai import AsyncOpenAI
from openai._types import NOT_GIVEN
from openai.types import CompletionUsage, ResponseFormatText, ResponseFormatJSONObject
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.completion_create_params import ResponseFormat

from pydantic import BaseModel

from kibernikto.bots.ai_settings import AI_SETTINGS
from kibernikto.interactors.tools import Toolbox
from kibernikto.plugins import KiberniktoPlugin
from kibernikto.utils import ai_tools
from kibernikto.utils.ai_tools import run_tool_calls


class OpenAiExecutorConfig(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    id: int = None
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
    tool_call_hole_deepness: int = AI_SETTINGS.OPENAI_TOOLS_DEEPNESS_LEVEL
    reaction_calls: list = ['никто', 'хонда', 'урод']
    tools: List[Toolbox] = []
    hide_errors: bool = False
    app_id: str = AI_SETTINGS.OPENAI_INSTANCE_ID


DEFAULT_CONFIG = OpenAiExecutorConfig()


class OpenAIRoles(str, Enum):
    system = 'system',
    user = 'user',
    assistant = 'assistant'
    tool = 'tool',


class OpenAIExecutor:
    """
    Basic Entity on the OpenAI library level.
    Sends requests and receives responses. Can store chat summary.
    Can process group chats at some point.
    """

    def __init__(self,
                 bored_after=0,
                 config=DEFAULT_CONFIG, unique_id=NOT_GIVEN,
                 client: AsyncOpenAI = None):
        self.bored_after = bored_after
        self.master_call = config.master_call
        self.reset_call = config.reset_call
        self.unique_id = unique_id
        self.summarize = config.max_words_before_summary != 0
        if client:
            self.client = client
            self.restrict_client_instance = True
        else:
            self.client = AsyncOpenAI(base_url=config.url, api_key=config.key, max_retries=DEFAULT_CONFIG.max_retries)
            self.restrict_client_instance = False

        self.model = config.model
        self.full_config = config

        # setting real max messages value: add some space for tools etc
        self._set_max_history_len(config)

        # user string messages preprocessing entities to go here
        self.plugins: List[KiberniktoPlugin] = []

        # additional tools in Toolbox formats
        self.tools: List[Toolbox] = config.tools
        self.use_system = True

        if self.max_messages < 2:
            self.max_messages = 2  # hahaha

        # default configuration. TODO: rework
        self._reset()

    @property
    def tools_definitions(self):
        return [toolbox.definition for toolbox in self.tools]

    @property
    def default_headers(self):
        return None

    @property
    def tools_names(self):
        return [toolbox.function_name for toolbox in self.tools]

    def _get_tool_implementation(self, name):
        for x in self.tools:
            if x.function_name == name:
                return x.implementation

    def _set_max_history_len(self, config: OpenAiExecutorConfig):
        history_len = config.max_messages
        if config.tools:
            history_len = config.max_messages + len(config.tools) * 2
        if config.max_messages % 2 == 0:
            self.max_messages = history_len
        else:
            self.max_messages = history_len + 1

    def process_usage(self, usage: CompletionUsage) -> dict | None:
        """
        Calculates usage costs if possible
        :param usage:
        :return: usage dict updated with costs
        """
        # logging.warning(f"usage is {usage}")
        if not usage:
            # logging.debug("usage unknown!")
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
            pass
            # logging.warning("no OPENAI_INPUT_PRICE (input_price) and OPENAI_OUTPUT_PRICE (output_price) provided")
        # logging.debug(f"process_usage: {usage_dict}")
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

    # FIXME: to be reworked
    async def heed(self, message, author=None):
        """
        Save message to history, but do not call OpenAI yet.
        :param message: recieved message
        :param author: outer chat message author
        :return:
        """
        self.reset_if_usercall(message)
        pass

    async def single_request(self, message, model=None, response_type: Literal['text', 'json_object'] = 'text',
                             additional_content: dict = None, max_tokens=None, temperature=None, use_system=True):
        this_message = dict(content=f"{message}", role=OpenAIRoles.user.value)

        if additional_content:
            this_message = {
                "role": "user",
                "content": [
                    {"type": "text", "text": message},
                    additional_content
                ]
            }

        response_format = {"type": response_type}

        completion_dict = dict(
            model=self.model if not model else model,
            response_format=response_format,
            extra_headers=self.default_headers
        )

        max_output_tokens = max_tokens if max_tokens else self.full_config.max_tokens

        system_prompt_enabled = use_system if use_system else self.use_system

        if system_prompt_enabled:
            messages = [self.about_me, this_message]
            completion_dict['max_tokens'] = max_output_tokens
            completion_dict['temperature'] = temperature if temperature else self.full_config.temperature
        else:
            messages = [this_message]
            completion_dict['max_completion_tokens'] = max_output_tokens

        completion_dict['messages'] = messages

        completion: ChatCompletion = await self.client.chat.completions.create(**completion_dict)
        choice: Choice = completion.choices[0]
        usage_dict = self.process_usage(completion.usage)
        return choice, usage_dict

    async def _run_for_messages(self, full_prompt, author=NOT_GIVEN,
                                response_type: Literal['text', 'json_object'] = 'text', model: str = None):
        tools_to_use = self.tools_definitions if self.tools_definitions else NOT_GIVEN

        if not full_prompt:
            raise ValueError("full_prompt cannot be empty")

        if not model:
            model = self.model

        # Need to be sure the prompt is fine
        system_message = [full_prompt[0]] if full_prompt[0]['role'] == 'system' else []
        response_format = {"type": response_type}
        conversation_messages = full_prompt[1:] if system_message else full_prompt
        # can not start with tool result, for example
        filtered_messages = self.prepare_message_prompt(conversation_messages)

        completion_dict = dict(
            model=model,
            # user=f"{author}",
            tools=tools_to_use,
            response_format=response_format,
            extra_headers=self.default_headers
        )

        if self.use_system:
            final_prompt = system_message + filtered_messages
            completion_dict['max_tokens'] = self.full_config.max_tokens
            completion_dict['temperature'] = self.full_config.temperature
        else:
            final_prompt = filtered_messages
            completion_dict['max_completion_tokens'] = self.full_config.max_tokens * 5

        completion_dict['messages'] = final_prompt

        try:
            completion: ChatCompletion = await self.client.chat.completions.create(**completion_dict)
        except Exception as e:
            pprint.pprint(f"{final_prompt}")
            raise e

        choice: Choice = completion.choices[0]
        usage_dict = self.process_usage(completion.usage)
        return choice, usage_dict

    async def heed_and_reply(self, **kwargs):
        return await self.request_llm(**kwargs)

    async def request_llm(self, message: str, author=NOT_GIVEN, save_to_history=True,
                          response_type: Literal['text', 'json_object'] = 'text',
                          additional_content: dict = None, with_history: bool = True,
                          custom_model: str = None) -> str:
        """
        Sends message to OpenAI and receives response. Can preprocess user message and work before actual API call.
        :param custom_model: is to use model not equal to default executor ones. Can break the tools!
        :param additional_content: for example type: image_url
        :param response_type:
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

        if additional_content:
            this_message = {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    additional_content
                ]
            }

        await self._aware_overflow()

        if with_history:
            messages_to_use = list(self.messages)
        else:
            messages_to_use = []

        prompt = [self.get_cur_system_message()] + messages_to_use + [this_message]

        # logging.debug(f"sending {prompt}")

        choice, usage = await self._run_for_messages(full_prompt=prompt, author=author, response_type=response_type,
                                                     model=custom_model)
        response_message: ChatCompletionMessage = choice.message

        if ai_tools.is_function_call(choice=choice):
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

    def prepare_message_prompt(self, messages_to_check: list) -> list:
        messages_list: list = messages_to_check.copy()

        def is_bad_first_message() -> bool:
            if not len(messages_list):
                return False
            first_message = messages_list[0]
            return first_message['role'] != 'user'

        while is_bad_first_message():
            # print(f"removing 0 message:")
            # pprint.pprint(messages_list[0])
            messages_list.pop(0)

        return messages_list

    def _ensure_no_tool_results_orphans(self, prompt: list = ()):
        """
        Not me, OpenAI did this. We need to be sure we do not have lost tool call results in history
        if the actual request moved upper. Performs the actual clearance.
        :return:
        """

    def _reset(self, clear_persistent_history=False):
        """
        Resetting the history
        :param clear_persistent_history: to be used in child instances
        :return:
        """
        # never gets full, +1 for system

        self.messages = deque(maxlen=self.max_messages)

        wai = self.full_config.who_am_i.format(self.full_config.name)

        self.about_me = dict(role=OpenAIRoles.system.value, content=f"{wai}")

    async def needs_attention(self, message):
        """checks if the reaction needed for the given message"""
        return self.should_react(message)

    async def process_tool_calls(self, choice: Choice, original_request_text: str, save_to_history=True, iteration=0):
        """

        :param choice:
        :param original_request_text:
        :param save_to_history:
        :param iteration: for chain calls to know how deep we are
        :return:
        """

        if iteration > self.full_config.tool_call_hole_deepness:
            # raise BrokenPipeError("RECURSION ALERT: Too much tool calls. Stop the boat!")
            return "RECURSION ALERT: Too much recursive tool calls. Stop the boat!"
        prompt = list(self.messages)

        message_dict = None

        if original_request_text:
            # if is None it's a tool call
            message_dict = dict(content=f"{original_request_text}", role=OpenAIRoles.user.value)
            prompt.append(message_dict)

        tool_call_messages = await run_tool_calls(choice=choice, available_tools=self.tools, unique_id=self.unique_id)

        choice, usage = await self._run_for_messages(
            full_prompt=[self.get_cur_system_message()] + prompt + tool_call_messages)
        response_message: ChatCompletionMessage = choice.message

        if message_dict and save_to_history:
            self.save_to_history(message_dict, usage_dict=usage)
        for tool_call_message in tool_call_messages:
            self.save_to_history(tool_call_message, usage_dict=usage)
        if response_message.content and save_to_history:
            response_message_dict = dict(content=f"{response_message.content}", role=OpenAIRoles.assistant.value)
            self.save_to_history(response_message_dict, usage_dict=usage)

        if ai_tools.is_function_call(choice=choice):
            if response_message.content:
                print(f"!!!{response_message.content}")
            return await self.process_tool_calls(choice, None, iteration=iteration + 1)
        elif response_message.content:
            return response_message.content
        else:
            return f"I did everything, but with no concrete result unfortunately"

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
            obj["role"] not in [OpenAIRoles.system.value] and obj["content"] is not None and
            isinstance(obj['content'], str))
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
