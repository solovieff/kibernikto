"""Offline tests for the read-only Logfire history adapter (OTel span replay, no network)."""

import asyncio
import json
import os
import unittest
from datetime import UTC, datetime, timedelta

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart

from kibernikto.config import APP_SETTINGS
from kibernikto.storage.logfire.history import (LogfireHistoryError, LogfireHistoryStorage, otel_to_model_messages,
                                                stitch_spans)


def _user(text: str) -> dict:
    return {'role': 'user', 'parts': [{'type': 'text', 'content': text}]}


def _assistant(text: str) -> dict:
    return {'role': 'assistant', 'parts': [{'type': 'text', 'content': text}]}


class _FakeClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.sql: list[str] = []

    async def __aenter__(self) -> '_FakeClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def query_json_rows(self, sql: str, **kwargs: object) -> dict:
        self.sql.append(sql)
        return {'columns': [], 'rows': self.rows}


def _row(start: str, messages: list[dict]) -> dict:
    return {
        'span_name': 'invoke_agent kibernikto-agent',
        'start_timestamp': start,
        'attributes': {'pydantic_ai.all_messages': json.dumps(messages)},
    }


class OtelReplayTests(unittest.TestCase):
    def test_translates_user_assistant_and_tool_pairs(self) -> None:
        messages = [
            {'role': 'user', 'parts': [{'type': 'text', 'content': 'hi'}]},
            {'role': 'assistant', 'parts': [
                {'type': 'thinking', 'content': 'hmm'},
                {'type': 'tool_call', 'id': 'c1', 'name': 'lookup', 'arguments': {'q': 'x'}},
            ]},
            {'role': 'user', 'parts': [{'type': 'tool_call_response', 'id': 'c1', 'name': 'lookup', 'result': 'ok'}]},
            {'role': 'assistant', 'parts': [{'type': 'text', 'content': 'done'}]},
        ]
        result = otel_to_model_messages(messages)

        self.assertIsInstance(result[0], ModelRequest)
        self.assertIsInstance(result[0].parts[0], UserPromptPart)
        self.assertEqual(result[0].parts[0].content, 'hi')
        self.assertIsInstance(result[1], ModelResponse)
        self.assertEqual(result[1].parts[0].content, 'hmm')
        self.assertIsInstance(result[1].parts[1], ToolCallPart)
        self.assertEqual((result[1].parts[1].tool_name, result[1].parts[1].args, result[1].parts[1].tool_call_id),
                         ('lookup', {'q': 'x'}, 'c1'))
        self.assertIsInstance(result[2].parts[0], ToolReturnPart)
        self.assertEqual((result[2].parts[0].tool_call_id, result[2].parts[0].content), ('c1', 'ok'))
        self.assertIsInstance(result[3].parts[0], TextPart)
        self.assertEqual(result[3].parts[0].content, 'done')

    def test_drops_empty_and_unknown_roles(self) -> None:
        result = otel_to_model_messages([{'role': 'system', 'parts': [{'type': 'text', 'content': 's'}]},
                                         {'role': 'user', 'parts': []}])
        self.assertEqual(result, [])

    def test_stitch_merges_overlapping_windows(self) -> None:
        a, b, c = _user('a'), _user('b'), _user('c')
        merged = stitch_spans([[a, b], [b, c], [c]])
        self.assertEqual(merged, [a, b, c])

    def test_stitch_keeps_repeated_short_lines_without_overlap(self) -> None:
        ok = _user('ok')
        merged = stitch_spans([[ok], [ok]])
        self.assertEqual(len(merged), 1)


class LogfireHistoryStorageTests(unittest.TestCase):
    def _storage(self, rows: list[dict]) -> tuple[LogfireHistoryStorage, _FakeClient]:
        client = _FakeClient(rows)
        return LogfireHistoryStorage(name='kibernikto-agent', read_token='test', client_factory=lambda: client), client

    def test_requires_token_without_factory(self) -> None:
        previous = os.environ.pop('LOGFIRE_READ_TOKEN', None)
        try:
            with self.assertRaises(LogfireHistoryError):
                LogfireHistoryStorage(name='x')
        finally:
            if previous is not None:
                os.environ['LOGFIRE_READ_TOKEN'] = previous

    def test_query_filters_by_agent_and_conversation(self) -> None:
        storage, client = self._storage([])
        asyncio.run(storage.get_conversation('42'))
        sql = client.sql[0]
        self.assertIn("'kibernikto-agent'", sql)
        self.assertIn("'42'", sql)
        self.assertIn('pydantic_ai.all_messages', sql)
        self.assertIn(f"service_name = '{APP_SETTINGS.INSTANCE_NAME}'", sql)

    def test_query_filters_by_custom_service_name(self) -> None:
        client = _FakeClient([])
        storage = LogfireHistoryStorage(name='kibernikto-agent', service_name='kibernikto-dev',
                                        read_token='test', client_factory=lambda: client)
        asyncio.run(storage.get_conversation('42'))
        self.assertIn("service_name = 'kibernikto-dev'", client.sql[0])

    def test_get_conversation_returns_window_of_latest_span(self) -> None:
        now = datetime.now(UTC)
        older = [_user('old'), _assistant('old-answer')]
        newer = [_user('old'), _assistant('old-answer'), _user('new'), _assistant('new-answer')]
        rows = [
            _row((now - timedelta(minutes=5)).isoformat(), older),
            _row((now - timedelta(minutes=1)).isoformat(), newer),
        ]
        storage, _ = self._storage(rows)
        window = asyncio.run(storage.get_conversation('42'))
        self.assertEqual(window[-1].parts[0].content, 'new-answer')

    def test_get_full_conversation_stitches_all_spans(self) -> None:
        now = datetime.now(UTC)
        rows = [
            _row((now - timedelta(minutes=2)).isoformat(), [_user('1'), _assistant('a1')]),
            _row((now - timedelta(minutes=1)).isoformat(), [_assistant('a1'), _user('2'), _assistant('a2')]),
        ]
        storage, _ = self._storage(rows)
        full = asyncio.run(storage.get_full_conversation('42'))
        texts = [part.content for msg in full for part in msg.parts]
        self.assertEqual(texts, ['1', 'a1', '2', 'a2'])

    def test_add_is_noop(self) -> None:
        storage, client = self._storage([])
        self.assertIsNone(asyncio.run(storage.add_messages('42', [_user('x')])))
        self.assertEqual(client.sql, [])

    def test_reset_cutoff_hides_older_spans(self) -> None:
        now = datetime.now(UTC)
        rows = [_row((now - timedelta(minutes=2)).isoformat(), [_user('old'), _assistant('old-answer')])]
        storage, _ = self._storage(rows)
        asyncio.run(storage.replace_messages('42', []))
        window = asyncio.run(storage.get_conversation('42'))
        self.assertEqual([part.content for msg in window for part in msg.parts], [])
        full = asyncio.run(storage.get_full_conversation('42'))
        self.assertEqual([part.content for msg in full for part in msg.parts], [])

    def test_partial_replace_is_skipped(self) -> None:
        now = datetime.now(UTC)
        rows = [_row((now - timedelta(minutes=1)).isoformat(), [_user('old'), _assistant('old-answer')])]
        storage, _ = self._storage(rows)
        asyncio.run(storage.replace_messages('42', [ModelRequest(parts=[UserPromptPart(content='kept')])]))
        window = asyncio.run(storage.get_conversation('42'))
        self.assertEqual(window[0].parts[0].content, 'old')


if __name__ == '__main__':
    unittest.main()
