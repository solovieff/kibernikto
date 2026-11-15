"""Read-only ``HistoryStorage`` rebuilt from Logfire agent-run spans (``pydantic_ai.all_messages``)."""

import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from logfire.query_client import AsyncLogfireQueryClient
from pydantic_ai.messages import (AudioUrl, DocumentUrl, ImageUrl, ModelMessage, ModelRequest, ModelResponse,
                                  TextPart, ThinkingPart, ToolCallPart, ToolReturnPart, UserPromptPart, VideoUrl)

from kibernikto.config import APP_SETTINGS
from kibernikto.storage.base import _DEFAULT_HISTORY_SIZE, _window

logger = logging.getLogger(__name__)

_URL_PARTS = {"image": ImageUrl, "audio": AudioUrl, "video": VideoUrl}
_SPAN_FETCH_LIMIT = 1000
_LATEST_FETCH_LIMIT = 20
_LOGFIRE_TOKEN_ENV = "LOGFIRE_READ_TOKEN"


class LogfireClient(Protocol):
    async def __aenter__(self) -> "LogfireClient": ...

    async def __aexit__(self, *exc: object) -> None: ...

    async def query_json_rows(self, sql: str, *, min_timestamp: datetime, max_timestamp: datetime | None = None,
                              limit: int | None = None, timezone: str | None = None,
                              environment: str | list[str] | None = None) -> dict[str, Any]: ...


class LogfireHistoryError(RuntimeError):
    """Logfire history backend misuse or missing configuration."""


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _as_datetime(value: datetime | str) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _span_messages(attributes: dict[str, Any] | str) -> list[dict[str, Any]]:
    attrs = json.loads(attributes) if isinstance(attributes, str) else attributes
    raw = attrs.get("pydantic_ai.all_messages")
    if isinstance(raw, str):
        raw = json.loads(raw)
    return list(raw or [])


def _overlap(previous: list[str], new: list[str]) -> int:
    """Longest suffix of ``previous`` equal to a prefix of ``new``."""
    for size in range(min(len(previous), len(new)), 0, -1):
        if previous[-size:] == new[:size]:
            return size
    return 0


def stitch_spans(spans: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Merge per-run OTel message windows (oldest first) by their overlapping boundary."""
    merged: list[dict[str, Any]] = []
    keys: list[str] = []
    for window in spans:
        window_keys = [json.dumps(msg, sort_keys=True, ensure_ascii=False) for msg in window]
        shared = _overlap(keys, window_keys)
        merged.extend(window[shared:])
        keys.extend(window_keys[shared:])
    return merged


def _to_request_parts(parts: list[dict[str, Any]]) -> list[Any]:
    result: list[Any] = []
    for part in parts:
        kind = part.get("type")
        if kind == "text" and part.get("content"):
            result.append(UserPromptPart(content=part["content"]))
        elif kind == "tool_call_response":
            result.append(ToolReturnPart(tool_name=part["name"], content=part.get("result"), tool_call_id=part["id"]))
        elif kind == "uri" and part.get("uri"):
            url_cls = _URL_PARTS.get(part.get("modality", ""), DocumentUrl)
            result.append(url_cls(url=part["uri"]))
    return result


def _to_response_parts(parts: list[dict[str, Any]]) -> list[Any]:
    result: list[Any] = []
    for part in parts:
        kind = part.get("type")
        if kind == "text" and part.get("content"):
            result.append(TextPart(content=part["content"]))
        elif kind == "thinking" and part.get("content"):
            result.append(ThinkingPart(content=part["content"]))
        elif kind == "tool_call":
            result.append(ToolCallPart(tool_name=part["name"], args=part.get("arguments"), tool_call_id=part["id"]))
    return result


def otel_to_model_messages(messages: list[dict[str, Any]]) -> list[ModelMessage]:
    """Translate OTel GenAI messages (instrumentation v5) back into ``ModelMessage`` objects."""
    result: list[ModelMessage] = []
    for msg in messages:
        parts = msg.get("parts", [])
        role = msg.get("role")
        if role == "user":
            request_parts = _to_request_parts(parts)
            if request_parts:
                result.append(ModelRequest(parts=request_parts))
        elif role == "assistant":
            response_parts = _to_response_parts(parts)
            if response_parts:
                result.append(ModelResponse(parts=response_parts))
    return result


class LogfireHistoryStorage:  # satisfies HistoryStorage (structural)
    """Conversation history read from agent-run spans; ``replace_messages([])`` sets a process-local cutoff (spans are immutable)."""

    def __init__(
        self,
        *,
        name: str,
        history_size: int = _DEFAULT_HISTORY_SIZE,
        window_days: int = 30,
        service_name: str = APP_SETTINGS.INSTANCE_NAME,
        read_token: str | None = None,
        client_factory: Callable[[], LogfireClient] | None = None,
    ) -> None:
        token = read_token or os.environ.get(_LOGFIRE_TOKEN_ENV)
        if client_factory is None and not token:
            raise LogfireHistoryError(f"{_LOGFIRE_TOKEN_ENV} is not set")
        self._name = name
        self._service_name = service_name
        self._history_size = history_size
        self._window = timedelta(days=window_days)
        self._cutoffs: dict[str, datetime] = {}
        self._client_factory: Callable[[], LogfireClient] = client_factory or (
            lambda: AsyncLogfireQueryClient(token or "")
        )

    async def _fetch_spans(self, conversation_id: str, limit: int) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        sql = (
            "SELECT span_name, start_timestamp, attributes FROM records "
            f"WHERE span_name LIKE 'invoke_agent%' "
            f"AND service_name = {_sql_str(self._service_name)} "
            f"AND attributes->>'gen_ai.agent.name' = {_sql_str(self._name)} "
            f"AND attributes->>'gen_ai.conversation.id' = {_sql_str(conversation_id)} "
            "AND attributes ? 'pydantic_ai.all_messages' "
            "ORDER BY start_timestamp DESC"
        )
        async with self._client_factory() as client:
            result = await client.query_json_rows(sql, min_timestamp=now - self._window, max_timestamp=now, limit=limit)
        cutoff = self._cutoffs.get(conversation_id)
        rows = [row for row in result["rows"] if _span_messages(row["attributes"])]
        if cutoff is not None:
            rows = [row for row in rows if _as_datetime(row["start_timestamp"]) > cutoff]
        rows.sort(key=lambda row: _as_datetime(row["start_timestamp"]))
        return rows

    async def _messages(self, conversation_id: str, limit: int) -> list[ModelMessage]:
        rows = await self._fetch_spans(str(conversation_id), limit)
        stitched = stitch_spans([_span_messages(row["attributes"]) for row in rows])
        return otel_to_model_messages(stitched)

    async def get_conversation(self, conversation_id: str) -> list[ModelMessage]:
        latest = await self._fetch_spans(str(conversation_id), limit=_LATEST_FETCH_LIMIT)
        if not latest:
            return []
        return _window(otel_to_model_messages(_span_messages(latest[-1]["attributes"])), self._history_size)

    async def get_full_conversation(self, conversation_id: str, limit: int = 5000) -> list[ModelMessage]:
        return (await self._messages(str(conversation_id), _SPAN_FETCH_LIMIT))[-limit:]

    async def add_messages(self, conversation_id: str, messages: list[ModelMessage]) -> None:
        return None  # Agent-run spans are written by instrumentation; nothing to persist here.

    async def replace_messages(self, conversation_id: str, messages: list[ModelMessage]) -> None:
        cid = str(conversation_id)
        if messages:
            logger.warning("Logfire history cannot rewrite spans; partial replace for conversation %s skipped", cid)
            return None
        self._cutoffs[cid] = datetime.now(UTC)
