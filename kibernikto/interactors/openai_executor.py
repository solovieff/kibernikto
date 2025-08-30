import logging
from collections import deque
from enum import Enum
from typing import List, Literal

from openai import AsyncOpenAI
from openai._types import NOT_GIVEN
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from pydantic import BaseModel

from kibernikto.bots.ai_settings import AI_SETTINGS
from kibernikto.interactors.tools import Toolbox
from kibernikto.utils import ai_tools
from kibernikto.utils.ai_tools import run_tool_calls
from .openai_executor_utils import get_tool_implementation, calculate_max_messages, process_usage, has_pricing, \
    prepare_message_prompt, check_word_overflow


class OpenAiExecutorConfig(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    id: int | str = None
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
    master_call: str = "Mister kibernikto!"
    summarize_request: str | None = AI_SETTINGS.OPENAI_SUMMARY
    max_words_before_summary: int = AI_SETTINGS.OPENAI_MAX_WORDS
    tool_call_hole_deepness: int = AI_SETTINGS.OPENAI_TOOLS_DEEPNESS_LEVEL
    reaction_calls: list = ['никто', 'honda', 'кибер']
    tools: List[Toolbox] = []
    hide_errors: bool = False
    app_id: str = AI_SETTINGS.OPENAI_INSTANCE_ID
    tools_with_history: bool = True


DEFAULT_CONFIG = OpenAiExecutorConfig()


class OpenAIRoles(str, Enum):
    system = 'system',
    user = 'user',
    assistant = 'assistant'
    tool = 'tool',


class OpenAIExecutor:
    """
    Core entity on the OpenAI library level.
    Sends requests and receives responses.
    Deals with history, tool calling etc.
    Can process group chats at some point.
    """

    def __init__(self,
                 config=DEFAULT_CONFIG,
                 unique_id=NOT_GIVEN,
                 client: AsyncOpenAI = None, **kwargs):
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

        # additional tools in Toolbox formats
        self.tools: List[Toolbox] = config.tools
        self.use_system = True

        if self.max_messages < 2:
            self.max_messages = 2  # hahaha

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
        return get_tool_implementation(self)

    def _set_max_history_len(self, config: OpenAiExecutorConfig):
        self.max_messages = calculate_max_messages(config)

    def process_usage(self, usage: CompletionUsage) -> dict | None:
        """
        Calculates usage costs if possible
        :param usage:
        :return: usage dict updated with costs
        """
        if not usage:
            return None

        usage_dict = usage.model_dump()
        if has_pricing(self.full_config):
            usage_dict = process_usage(usage_dict, self)
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
            messages = [self.get_cur_system_message(), this_message]
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
        filtered_messages = prepare_message_prompt(conversation_messages)

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
            # pprint.pprint(f"{final_prompt}")
            raise e

        choice: Choice = completion.choices[0]
        usage_dict = self.process_usage(completion.usage)
        return choice, usage_dict

    async def heed_and_reply(self, **kwargs):
        return await self.request_llm(**kwargs)

    async def request_llm(self, message: str, author=NOT_GIVEN, save_to_history=True,
                          response_type: Literal['text', 'json_object'] = 'text',
                          additional_content: dict = None, with_history: bool = True,
                          custom_model: str = None, call_session_id: str = None) -> str:
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
            return await self.process_tool_calls(choice, user_message, call_session_id=call_session_id)

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

    def _reset(self, clear_persistent_history=False):
        """
        Resetting the history and filling in the system message dict
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

    async def process_tool_calls(self, choice: Choice, original_request_text: str, save_to_history=True, iteration=0,
                                 call_session_id: str = None):
        """

        :param call_session_id: current user call session id.
        :param choice:
        :param original_request_text:
        :param save_to_history:
        :param iteration: for chain calls to know how deep we are
        :return:
        """

        if iteration > self.full_config.tool_call_hole_deepness:
            # raise BrokenPipeError("RECURSION ALERT: Too much tool calls. Stop the boat!")
            return "RECURSION ALERT: Too much recursive tool calls. Stop the boat!"

        # using or not using previous dialogue in a tool call
        if self.full_config.tools_with_history:
            prompt = list(self.messages)
        else:
            prompt = []

        message_dict = None

        if original_request_text:
            # if is None it's a tool call
            message_dict = dict(content=f"{original_request_text}", role=OpenAIRoles.user.value)
            prompt.append(message_dict)

        tool_call_messages = await run_tool_calls(choice=choice, available_tools=self.tools, unique_id=self.unique_id,
                                                  call_session_id=call_session_id)

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
                logging.warning(f"Preliminary tool call comment: {response_message.content}")
            return await self.process_tool_calls(choice, None, iteration=iteration + 1)
        elif response_message.content:
            return response_message.content
        else:
            return f"I did everything, but with no concrete result unfortunately"

    async def _aware_overflow(self):
        """
        Checking if additional actions like cutting the message stack needed and doing it if needed.
        """
        words_check = check_word_overflow(list(self.messages), self.full_config.max_words_before_summary)
        if words_check or len(self.messages) > self.max_messages:
            self.messages.popleft()
            self.messages.popleft()
