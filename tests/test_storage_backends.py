"""Offline regressions for file/SQL history, media stores and S3 key mapping."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai.messages import (BinaryContent, FilePart, ModelRequest, ModelResponse,
                                  TextPart, ThinkingPart, UserPromptPart)


def _turn(text: str) -> list:
    return [ModelRequest(parts=[UserPromptPart(content=text)]),
            ModelResponse(parts=[TextPart(content=f'answer to {text}')])]


def _texts(messages: list) -> list[str]:
    out = []
    for msg in messages:
        for part in msg.parts:
            out.append(getattr(part, 'content', ''))
    return out


class FileHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from kibernikto.storage.file.history import FileStoreHistoryStorage
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.make = lambda: FileStoreHistoryStorage(name='t', history_size=4, root=self.root)
        self.storage = self.make()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_round_trip_is_durable_across_instances(self) -> None:
        await self.storage.add_messages(7, _turn('hello'))
        reloaded = self.make()
        full = await reloaded.get_full_conversation(7)
        self.assertEqual(_texts(full), ['hello', 'answer to hello'])
        self.assertTrue((self.root / 'history' / 't' / '7.json').exists())

    async def test_window_keeps_last_turns_aligned_to_request(self) -> None:
        for i in range(3):
            await self.storage.add_messages(1, _turn(f'q{i}'))
        window = await self.storage.get_conversation(1)
        self.assertEqual(window[0].kind, 'request')
        self.assertEqual(_texts(window)[-1], 'answer to q2')
        self.assertLessEqual(len(window), 4)

    async def test_histories_are_isolated_per_chat(self) -> None:
        await self.storage.add_messages(1, _turn('alpha'))
        await self.storage.add_messages(2, _turn('beta'))
        self.assertEqual(_texts(await self.storage.get_full_conversation(2)),
                         ['beta', 'answer to beta'])

    async def test_binary_parts_are_not_persisted(self) -> None:
        msgs = [ModelRequest(parts=[UserPromptPart(content='pic')]),
                ModelResponse(parts=[FilePart(content=BinaryContent(data=b'\x89PNG', media_type='image/png')),
                                     TextPart(content='done')])]
        await self.storage.add_messages(3, msgs)
        raw = (self.root / 'history' / 't' / '3.json').read_text(encoding='utf-8')
        self.assertNotIn('image/png', raw)
        self.assertNotIn('\\x89PNG', raw)

    async def test_thinking_is_dropped_by_default(self) -> None:
        msgs = [ModelRequest(parts=[UserPromptPart(content='q')]),
                ModelResponse(parts=[ThinkingPart(content='secret reasoning'), TextPart(content='a')])]
        await self.storage.add_messages(4, msgs)
        self.assertNotIn('secret reasoning', (self.root / 'history' / 't' / '4.json').read_text(encoding='utf-8'))

    async def test_replace_overwrites_stored_history(self) -> None:
        await self.storage.add_messages(3, _turn('old'))
        await self.storage.replace_messages(3, _turn('new'))
        self.assertEqual(_texts(await self.storage.get_full_conversation(3)), ['new', 'answer to new'])
        self.assertEqual(_texts(await self.make().get_full_conversation(3)), ['new', 'answer to new'])

    async def test_replace_tail_preserves_older_messages_beyond_window(self) -> None:
        await self.storage.add_messages(3, _turn('ancient'))
        await self.storage.add_messages(3, _turn('recent'))
        await self.storage.replace_messages(3, _turn('repaired'))
        self.assertEqual(
            _texts(await self.make().get_full_conversation(3)),
            ['ancient', 'answer to ancient', 'repaired', 'answer to repaired'],
        )

    async def test_corrupt_file_degrades_to_empty_history(self) -> None:
        path = self.root / 'history' / 't'
        path.mkdir(parents=True)
        (path / '5.json').write_text('{not json', encoding='utf-8')
        self.assertEqual(await self.storage.get_full_conversation(5), [])


class SqlHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from kibernikto.storage.sql import engine
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / 'history.db')
        self._patch = patch.object(engine.STORAGE_SETTINGS, 'SQLITE_PATH', self.db_path)
        self._patch.start()
        self._dsn = patch.object(engine.STORAGE_SETTINGS, 'DATA_BACKEND', 'sqlite')
        self._dsn.start()
        await engine.shutdown_db()
        await engine.ensure_db_initialized()
        from kibernikto.storage.sql.history import SqlHistoryStorage
        self.storage = SqlHistoryStorage(name='t', history_size=4)

    async def asyncTearDown(self) -> None:
        from kibernikto.storage.sql import engine
        await engine.shutdown_db()
        self._dsn.stop()
        self._patch.stop()
        self._tmp.cleanup()

    async def test_round_trip_and_window(self) -> None:
        for i in range(3):
            await self.storage.add_messages(9, _turn(f'q{i}'))
        window = await self.storage.get_conversation(9)
        self.assertEqual(window[0].kind, 'request')
        self.assertEqual(_texts(window)[-1], 'answer to q2')
        self.assertLessEqual(len(window), 4)

    async def test_sequence_continues_across_calls(self) -> None:
        await self.storage.add_messages(9, _turn('one'))
        await self.storage.add_messages(9, _turn('two'))
        full = await self.storage.get_full_conversation(9)
        self.assertEqual(_texts(full), ['one', 'answer to one', 'two', 'answer to two'])

    async def test_agent_namespaces_do_not_mix(self) -> None:
        from kibernikto.storage.sql.history import SqlHistoryStorage
        other = SqlHistoryStorage(name='other', history_size=4)
        await self.storage.add_messages(9, _turn('mine'))
        await other.add_messages(9, _turn('theirs'))
        self.assertEqual(_texts(await self.storage.get_full_conversation(9)), ['mine', 'answer to mine'])

    async def test_empty_add_is_noop(self) -> None:
        await self.storage.add_messages(10, [])
        self.assertEqual(await self.storage.get_full_conversation(10), [])

    async def test_replace_overwrites_only_this_namespace(self) -> None:
        from kibernikto.storage.sql.history import SqlHistoryStorage
        other = SqlHistoryStorage(name='other', history_size=4)
        await other.add_messages(9, _turn('theirs'))
        await self.storage.add_messages(9, _turn('old'))
        await self.storage.replace_messages(9, _turn('new'))
        self.assertEqual(_texts(await self.storage.get_full_conversation(9)), ['new', 'answer to new'])
        self.assertEqual(_texts(await other.get_full_conversation(9)), ['theirs', 'answer to theirs'])

    async def test_replace_tail_preserves_older_rows_beyond_window(self) -> None:
        await self.storage.add_messages(9, _turn('ancient'))
        await self.storage.add_messages(9, _turn('recent'))
        await self.storage.replace_messages(9, _turn('repaired'))
        self.assertEqual(
            _texts(await self.storage.get_full_conversation(9)),
            ['ancient', 'answer to ancient', 'repaired', 'answer to repaired'],
        )
        await self.storage.replace_messages(9, [])
        self.assertEqual(await self.storage.get_full_conversation(9), [])


class MediaFileStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from kibernikto.storage.file.media import MediaFileStore
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = MediaFileStore(self.root, name='default')

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_save_then_read_returns_same_bytes(self) -> None:
        ref = await self.store.save(42, b'payload', ext='png')
        self.assertTrue(ref.startswith('42/'))
        self.assertTrue(ref.endswith('.png'))
        self.assertEqual(await self.store.read(ref), b'payload')

    async def test_explicit_name_is_used(self) -> None:
        ref = await self.store.save(42, b'x', name='report.pdf')
        self.assertEqual(ref, '42/report.pdf')
        self.assertTrue((self.root / 'media' / 'default' / '42' / 'report.pdf').exists())

    async def test_exists_reflects_stored_files(self) -> None:
        ref = await self.store.save(42, b'x', name='a.jpg')
        self.assertTrue(await self.store.exists(ref))
        self.assertFalse(await self.store.exists('42/missing.jpg'))

    async def test_tmp_cleanup_is_idempotent(self) -> None:
        path = self.store.tmp_path('voice.ogg')
        path.write_bytes(b'v')
        type(self.store).cleanup_tmp(path)
        type(self.store).cleanup_tmp(path)
        self.assertFalse(path.exists())


class S3MediaStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from kibernikto.storage.s3.media import S3MediaStore
        self._tmp = tempfile.TemporaryDirectory()
        self.store = S3MediaStore(name='default')
        self.store._tmp_dir = Path(self._tmp.name) / 'tmp'
        self.client = AsyncMock()
        self.store._client = self.client

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_save_uses_namespaced_key_and_returns_ref(self) -> None:
        from kibernikto.storage.config import STORAGE_SETTINGS
        ref = await self.store.save(5, b'bytes', name='a.bin')
        self.assertEqual(ref, '5/a.bin')
        self.client.put_object.assert_awaited_once_with(
            Bucket=STORAGE_SETTINGS.S3_BUCKET, Key='media/default/5/a.bin', Body=b'bytes')

    async def test_read_fetches_same_key(self) -> None:
        body = AsyncMock()
        body.read.return_value = b'data'
        self.client.get_object.return_value = {'Body': body}
        self.assertEqual(await self.store.read('5/a.bin'), b'data')
        self.assertEqual(self.client.get_object.await_args.kwargs['Key'], 'media/default/5/a.bin')

    async def test_exists_true_on_head_success(self) -> None:
        self.assertTrue(await self.store.exists('5/a.bin'))
        self.assertEqual(self.client.head_object.await_args.kwargs['Key'], 'media/default/5/a.bin')

    async def test_exists_false_on_404_and_raises_other_errors(self) -> None:
        from botocore.exceptions import ClientError
        self.client.head_object.side_effect = ClientError({'Error': {'Code': '404'}}, 'HeadObject')
        self.assertFalse(await self.store.exists('5/a.bin'))
        self.client.head_object.side_effect = ClientError({'Error': {'Code': '403'}}, 'HeadObject')
        with self.assertRaises(ClientError):
            await self.store.exists('5/a.bin')

    async def test_tmp_stays_local(self) -> None:
        path = self.store.tmp_path('voice.ogg')
        self.assertEqual(path.parent, Path(self._tmp.name) / 'tmp')
        self.client.put_object.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()