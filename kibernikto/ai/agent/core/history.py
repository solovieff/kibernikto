from collections import defaultdict
from typing import List, Dict
from pydantic_ai.messages import ModelMessage
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS


class MemoryHistoryStorage:
    def __init__(self, history_size: int = AGENT_KIBERNIKTO_SETTINGS.HISTORY_SIZE):
        self._storage: Dict[int, List[ModelMessage]] = defaultdict(list)
        self._history_size = history_size

    def get_conversation(self, chat_id: int) -> List[ModelMessage]:
        messages: List[ModelMessage] = self._storage[chat_id]
        if not messages:
            return []

        # Начинаем с окна HISTORY_SIZE
        start_index = max(0, len(messages) - self._history_size)

        while start_index > 0 and messages[start_index].kind != 'request':
            start_index -= 1

        # Если мы дошли до 0 и всё ещё не пользователь, то берём как есть или ищем вперёд?
        # По условию: "первым всегда должно идти сообщение от пользователя".
        # Если в истории вообще нет сообщений от пользователя (что странно), вернём пустой список или с первого попавшегося пользователя.
        while start_index < len(messages) and messages[start_index].kind != 'request':
            start_index += 1

        return messages[start_index:]

    def add_messages(self, chat_id: int, messages: List[ModelMessage]):
        self._storage[chat_id].extend(messages)


history_storage = MemoryHistoryStorage()
