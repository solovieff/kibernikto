import dataclasses
from collections import defaultdict
from typing import Dict, List, Protocol, runtime_checkable

from pydantic_ai.messages import FilePart, ModelMessage, ModelRequest, ModelResponse, ThinkingPart

_DEFAULT_HISTORY_SIZE = 6


def _sanitize(messages: List[ModelMessage], *, keep_thinking: bool = False) -> List[ModelMessage]:
    """Drop instructions, binaries and reasoning so persisted history stays small.

    * ``ModelRequest.instructions`` — re-resolved every turn by
      ``pydantic_ai`` (``_agent_graph._prepare_request`` → ``_get_instructions``).
      The provider never reads historical ``instructions`` —
      ``models/__init__.py:_get_instruction_parts`` prefers
      ``model_request_parameters.instruction_parts`` and only falls back to
      ``message.instructions`` for bare ``model.request()`` callers.
      Persisting them just bloats JSON and burns tokens on replay.
      The only code that actually rehydrates them is the ``suspended``-turn
      resume path (Anthropic ``pause_turn`` / OpenAI background), which our
      Telegram bot never hits (it always sends a fresh prompt → ``UserError``
      on a suspended tail instead).
    * ``FilePart`` — bytes live in the media store, not history.
    * ``ThinkingPart`` — replayed to the provider on every turn; keep only
      when ``keep_thinking`` is set (signature is always dropped).
    """
    cleaned: List[ModelMessage] = []
    for msg in messages:
        if isinstance(msg, ModelRequest) and msg.instructions is not None:
            msg = dataclasses.replace(msg, instructions=None)
        if isinstance(msg, ModelResponse):
            parts = []
            for part in msg.parts:
                if isinstance(part, FilePart):
                    continue  # bytes live in the media store, not history
                if isinstance(part, ThinkingPart):
                    if not keep_thinking:
                        continue  # reasoning is replayed — don't store it
                    if part.signature:
                        part = dataclasses.replace(part, signature=None)
                parts.append(part)
            if len(parts) != len(msg.parts):
                msg = dataclasses.replace(msg, parts=parts)
        cleaned.append(msg)
    return cleaned


def _window(messages: List[ModelMessage], history_size: int) -> List[ModelMessage]:
    """Slice last ``history_size`` messages, aligned to a ``request`` boundary."""
    if not messages:
        return []
    start_index = max(0, len(messages) - history_size)
    while start_index > 0 and messages[start_index].kind != "request":
        start_index -= 1
    while start_index < len(messages) and messages[start_index].kind != "request":
        start_index += 1
    return messages[start_index:]


@runtime_checkable
class HistoryStorage(Protocol):
    """Any per-chat history backend — in-memory, file, postgres, etc."""

    def get_conversation(self, chat_id: int) -> List[ModelMessage]: ...

    def add_messages(self, chat_id: int, messages: List[ModelMessage]) -> None: ...


class MemoryHistoryStorage:
    """In-memory per-chat store (lost on restart). One impl of ``HistoryStorage``."""

    def __init__(
        self, history_size: int = _DEFAULT_HISTORY_SIZE, *, keep_thinking: bool = False
    ) -> None:
        self._storage: Dict[int, List[ModelMessage]] = defaultdict(list)
        self._history_size = history_size
        self._keep_thinking = keep_thinking

    def get_conversation(self, chat_id: int) -> List[ModelMessage]:
        return _window(self._storage[chat_id], self._history_size)

    def add_messages(self, chat_id: int, messages: List[ModelMessage]) -> None:
        self._storage[chat_id].extend(messages)
        self._storage[chat_id] = _sanitize(self._storage[chat_id], keep_thinking=self._keep_thinking)
