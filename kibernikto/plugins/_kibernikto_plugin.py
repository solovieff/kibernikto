from abc import ABC, abstractmethod


class KiberniktoPlugin(ABC):
    def __init__(self, post_process_reply=False):
        self.post_process_reply = post_process_reply

    @abstractmethod
    async def run_for_message(self, message: str) -> str:
        pass
