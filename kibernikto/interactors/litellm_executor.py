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

from .openai_executor import OpenAIExecutor, DEFAULT_CONFIG


class LiteLLMExecutor(OpenAIExecutor):
    """
    Basic Entity on the OpenAI library level.
    Sends requests and receives responses. Can store chat summary.
    Can process group chats at some point.
    """

    def __init__(self,
                 config=DEFAULT_CONFIG, **kwargs):
        purified_model = config.model
        if "/" in purified_model:
            purified_model = self.model.split("/")[1]

        super().__init__(config=config, custom_client=None, **kwargs)
