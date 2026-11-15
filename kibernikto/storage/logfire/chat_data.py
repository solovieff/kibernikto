"""``ChatDataStore`` that reads state back from the ``chat_data`` records ``LoggedChatData`` emits on every save."""

import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from logfire.query_client import AsyncLogfireQueryClient

from kibernikto.config import APP_SETTINGS
from kibernikto.storage.base import CHAT_DATA_RECORD, emit_chat_data
from kibernikto.storage.logfire.history import _LOGFIRE_TOKEN_ENV, LogfireClient, LogfireHistoryError, _sql_str
from kibernikto.storage.models import ConversationInfo

logger = logging.getLogger(__name__)


def _attributes(raw: dict[str, Any] | str) -> dict[str, Any]:
    return json.loads(raw) if isinstance(raw, str) else raw


class LogfireChatDataStorage:  # satisfies ChatDataStore (structural)
    """Append-only snapshots: the newest ``chat_data`` record per conversation wins; saves are cached write-through."""

    def __init__(
        self,
        *,
        window_days: int = 90,
        service_name: str = APP_SETTINGS.INSTANCE_NAME,
        read_token: str | None = None,
        client_factory: Callable[[], LogfireClient] | None = None,
    ) -> None:
        token = read_token or os.environ.get(_LOGFIRE_TOKEN_ENV)
        if client_factory is None and not token:
            raise LogfireHistoryError(f"{_LOGFIRE_TOKEN_ENV} is not set")
        self._service_name = service_name
        self._window = timedelta(days=window_days)
        self._cache: dict[str, ConversationInfo] = {}  # Span export lags: our own last write beats any query.
        self._client_factory: Callable[[], LogfireClient] = client_factory or (
            lambda: AsyncLogfireQueryClient(token or "")
        )

    async def _latest(self, conversation_id: str) -> ConversationInfo | None:
        now = datetime.now(UTC)
        sql = (
            "SELECT start_timestamp, attributes FROM records "
            f"WHERE span_name = {_sql_str(CHAT_DATA_RECORD)} "
            f"AND service_name = {_sql_str(self._service_name)} "
            f"AND attributes->>'conversation_id' = {_sql_str(conversation_id)} "
            "ORDER BY start_timestamp DESC"
        )
        async with self._client_factory() as client:
            result = await client.query_json_rows(sql, min_timestamp=now - self._window, max_timestamp=now, limit=1)
        rows = result["rows"]
        if not rows:
            return None
        attrs = _attributes(rows[0]["attributes"])
        return ConversationInfo.model_validate({k: attrs[k] for k in ("credits", "response_mode") if k in attrs})

    async def load(self, conversation_id: str) -> ConversationInfo:
        cid = str(conversation_id)
        cached = self._cache.get(cid)
        if cached is not None:
            return cached.model_copy()
        try:
            info = await self._latest(cid)
        except Exception:  # Degraded beats broken: serve defaults, uncached, so the next load retries.
            logger.exception("Chat data query failed for %s, using defaults", cid)
            return ConversationInfo()
        if info is None:
            info = ConversationInfo()
            await self.save(cid, info)
            emit_chat_data(cid, info)  # Query succeeded and found nothing: safe to record the defaults.
            return info
        self._cache[cid] = info
        return info.model_copy()

    async def save(self, conversation_id: str, info: ConversationInfo) -> None:
        cid = str(conversation_id)
        self._cache[cid] = info.model_copy()  # The record itself is emitted by the LoggedChatData wrapper.
