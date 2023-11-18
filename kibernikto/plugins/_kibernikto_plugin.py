from abc import ABC, abstractmethod

from openai import AsyncOpenAI


class KiberniktoPlugin(ABC):
    """
    Plugins get message as input and return processed message as output or None.
    """
    def __init__(self, model: str, base_url: str, api_key: str,
                 base_message: str, post_process_reply=False,
                 store_reply=False):
        """

        :param model:
        :param base_url:
        :param api_key:
        :param base_message:
        :param post_process_reply: if plugin reply should be used as input for further actions (i.e. other plugins)
        :param store_reply: if the result should be stored in the messages storage at bot level
        """
        self.post_process_reply = post_process_reply
        self.store_reply = store_reply

        self.model = model
        self.base_message = base_message
        self.client_async = AsyncOpenAI(base_url=base_url, api_key=api_key)

    @abstractmethod
    async def run_for_message(self, message: str) -> str:
        pass
