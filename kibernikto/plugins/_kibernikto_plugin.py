from abc import ABC, abstractmethod
from openai import AsyncOpenAI


class KiberniktoPluginException(Exception):
    def __init__(self, plugin_name: str, error_message: str):
        self.plugin_name = plugin_name
        super().__init__(error_message)


class KiberniktoPlugin(ABC):
    """
    Plugins gets message as input and returns processed message as output or None.
    """

    @staticmethod
    @abstractmethod
    def applicable():
        return False

    def __init__(self, model: str, base_url: str, api_key: str,
                 base_message: str, post_process_reply=False,
                 store_reply=False):
        """

        :param model:
        :param base_url:
        :param api_key:
        :param base_message:
        :param post_process_reply: if plugin reply should be used as input for further actions (i.e. other plugins or final ai message)
        :param store_reply: if the result should be stored in the messages storage at bot level
        """
        self.post_process_reply = post_process_reply
        self.store_reply = store_reply

        self.model = model
        self.base_message = base_message
        self.base_url = base_url
        self.client_async = AsyncOpenAI(base_url=base_url, api_key=api_key)

    @abstractmethod
    async def run_for_message(self, message: str) -> str:
        pass
