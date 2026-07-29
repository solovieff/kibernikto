from collections import defaultdict
from typing import Dict, List

from pydantic_ai.messages import ModelMessage

_DEFAULT_HISTORY_SIZE = 6


class MemoryHistoryStorage:
    """In-memory per-chat conversation store (lost on restart).

    ``get_conversation`` returns the last ``history_size`` messages, trimmed
    backwards until it starts on a ``'request'`` (user) message so the model
    always sees a valid conversation window.
    """

    def __init__(self, history_size: int = _DEFAULT_HISTORY_SIZE) -> None:
        self._storage: Dict[int, List[ModelMessage]] = defaultdict(list)
        self._history_size = history_size

    def get_conversation(self, chat_id: int) -> List[ModelMessage]:
        messages: List[ModelMessage] = self._storage[chat_id]
        if not messages:
            return []

        # Start with the last `history_size` messages.
        start_index = max(0, len(messages) - self._history_size)

        # Walk back until we land on a user request (never split a pair).
        while start_index > 0 and messages[start_index].kind != "request":
            start_index -= 1

        # Safety: if somehow still not on a request, scan forward to the first one.
        while start_index < len(messages) and messages[start_index].kind != "request":
            start_index += 1

        return messages[start_index:]

    def add_messages(self, chat_id: int, messages: List[ModelMessage]) -> None:
        self._storage[chat_id].extend(messages)