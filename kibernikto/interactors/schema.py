import abc
from typing import List, Optional, Any

from litellm import acompletion
from pydantic import BaseModel, Field, HttpUrl


class KiberniktoCompletions(BaseModel):
    api_key: str
    max_retries: int
    base_url: HttpUrl | None

    async def create(
            self,
            model: Optional[str],
            temperature: float,
            max_tokens: int,
            messages: List[dict],
            tools: list[dict] = [],
            response_format: dict = dict(type="text"),
            max_retries: int = 3,
            **kwargs
    ):
        print(f'this is a fake! {messages}')
        pass


class KiberniktoChat(BaseModel):
    completions: KiberniktoCompletions = None


class KiberniktoAIClient(BaseModel):
    api_key: str
    max_retries: int
    base_url: HttpUrl | None
    chat: KiberniktoChat = Field(default_factory=KiberniktoChat)

    async def close(self):
        print('client closed')


class LiteLLMChatCompletions(KiberniktoCompletions):
    api_key: str
    max_retries: int
    base_url: HttpUrl | None

    async def create(
            self,
            model: Optional[str],
            temperature: float,
            max_tokens: int,
            messages: List[dict],
            tools: list[dict] = [],
            response_format: dict = dict(type="text"),
            max_retries: int = 3,
            drop_params: bool = True,
            **kwargs
    ):
        return await acompletion(
            api_key=self.api_key,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tools=tools,
            drop_params=drop_params,
            **kwargs
        )


class LiteLLMAIClient(KiberniktoAIClient):
    async def close(self):
        print('client closed')

    def model_post_init(self, __context: Any) -> None:
        completions = LiteLLMChatCompletions(api_key=self.api_key, base_url=self.base_url, max_retries=self.max_retries)
        self.chat = KiberniktoChat(completions=completions)

    async def close(self):
        print('LiteLLMAIClient closed')
