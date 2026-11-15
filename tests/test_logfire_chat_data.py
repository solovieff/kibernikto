"""Offline tests for the Logfire chat_data adapter (log record on save, query on cold load)."""

import asyncio
import os
import unittest
from unittest import mock

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

import kibernikto.ai.agent  # noqa: F401  # Agent package first: storage.models <-> harness import cycle.
from kibernikto.storage.base import LoggedChatData
from kibernikto.storage.logfire.chat_data import LogfireChatDataStorage
from kibernikto.storage.models import ConversationInfo


class _FakeClient:
    def __init__(self, rows: list[dict], error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.sql: list[str] = []

    async def __aenter__(self) -> '_FakeClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def query_json_rows(self, sql: str, **kwargs: object) -> dict:
        self.sql.append(sql)
        if self.error:
            raise self.error
        return {'columns': [], 'rows': self.rows}


def _storage(client: _FakeClient) -> LogfireChatDataStorage:
    return LogfireChatDataStorage(read_token='test', client_factory=lambda: client)


class LogfireChatDataTests(unittest.TestCase):
    def test_wrapper_emits_log_record_for_any_backend(self) -> None:
        inner = mock.AsyncMock()
        with mock.patch('kibernikto.storage.base.logfire.info') as info:
            asyncio.run(LoggedChatData(inner).save(42, ConversationInfo(credits=7, response_mode='audio')))
        inner.save.assert_awaited_once()
        info.assert_called_once_with('chat_data', conversation_id='42', credits=7, response_mode='audio')

    def test_wrapper_snapshots_first_load_once(self) -> None:
        inner = mock.AsyncMock()
        inner.load.return_value = ConversationInfo(credits=5)
        wrapped = LoggedChatData(inner)

        async def scenario() -> None:
            await wrapped.load(42)
            await wrapped.load(42)

        with mock.patch('kibernikto.storage.base.logfire.info') as info:
            asyncio.run(scenario())
        info.assert_called_once_with('chat_data', conversation_id='42', credits=5, response_mode='text')

    def test_wrapper_skips_load_snapshot_when_disabled(self) -> None:
        inner = mock.AsyncMock()
        inner.load.return_value = ConversationInfo()
        with mock.patch('kibernikto.storage.base.logfire.info') as info:
            asyncio.run(LoggedChatData(inner, snapshot_on_load=False).load(42))
        info.assert_not_called()

    def test_cold_load_reads_latest_record(self) -> None:
        client = _FakeClient([{'start_timestamp': 'x', 'attributes': {'credits': 321, 'response_mode': 'audio'}}])
        info = asyncio.run(_storage(client).load('42'))
        self.assertEqual((info.credits, info.response_mode), (321, 'audio'))
        self.assertIn("span_name = 'chat_data'", client.sql[0])
        self.assertIn("'42'", client.sql[0])

    def test_cold_load_accepts_json_string_attributes(self) -> None:
        client = _FakeClient([{'start_timestamp': 'x', 'attributes': '{"credits": 5, "response_mode": "text"}'}])
        self.assertEqual(asyncio.run(_storage(client).load('42')).credits, 5)

    def test_save_beats_stale_query(self) -> None:
        client = _FakeClient([{'start_timestamp': 'x', 'attributes': {'credits': 1, 'response_mode': 'text'}}])
        storage = _storage(client)

        async def scenario() -> ConversationInfo:
            await storage.save('42', ConversationInfo(credits=900))
            return await storage.load('42')

        info = asyncio.run(scenario())
        self.assertEqual(info.credits, 900)
        self.assertEqual(client.sql, [])

    def test_load_returns_independent_copy(self) -> None:
        storage = _storage(_FakeClient([{'start_timestamp': 'x', 'attributes': {'credits': 10}}]))

        async def scenario() -> int:
            first = await storage.load('42')
            first.credits = 0
            return (await storage.load('42')).credits

        self.assertEqual(asyncio.run(scenario()), 10)

    def test_unknown_conversation_gets_defaults_and_logs(self) -> None:
        storage = _storage(_FakeClient([]))
        with mock.patch('kibernikto.storage.base.logfire.info') as info:
            loaded = asyncio.run(storage.load('42'))
        self.assertEqual(loaded.credits, ConversationInfo().credits)
        info.assert_called_once()

    def test_query_failure_falls_back_to_defaults_without_caching(self) -> None:
        client = _FakeClient([], error=RuntimeError('boom'))
        storage = _storage(client)

        async def scenario() -> tuple[ConversationInfo, ConversationInfo]:
            with self.assertLogs('kibernikto.storage.logfire.chat_data', level='ERROR'):
                first = await storage.load('42')
            client.error = None
            client.rows = [{'start_timestamp': 'x', 'attributes': {'credits': 777}}]
            return first, await storage.load('42')

        failed, recovered = asyncio.run(scenario())
        self.assertEqual(failed.credits, ConversationInfo().credits)
        self.assertEqual(recovered.credits, 777)


if __name__ == '__main__':
    unittest.main()
