"""Offline coverage for voice transcription: JSON `.text` extraction and API errors as markers."""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram.types import Chat, File, Message, User, Voice

from kibernikto.telegram.pre_processors import _default
from kibernikto.telegram.pre_processors._default import TelegramMessagePreprocessor

VOICE = Voice(file_id='v', file_unique_id='vu', duration=3)


class FakeBot:
    async def get_file(self, file_id: str) -> File:
        return File(file_id=file_id, file_unique_id='vu', file_path='voice/a.oga')

    async def download_file(self, path: str, destination: str) -> None:
        Path(destination).write_bytes(b'ogg')


class VoiceTranscriptionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        store = SimpleNamespace(tmp_path=lambda name: Path(self.dir.name) / name, cleanup_tmp=lambda p: None)
        patcher = patch.object(_default, 'media_store', store)
        patcher.start()
        self.addCleanup(patcher.stop)
        key = patch.object(_default.SETTINGS, 'OPENAI_API_KEY', 'k')
        key.start()
        self.addCleanup(key.stop)
        self.pre = TelegramMessagePreprocessor()
        self.message = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=1, type='private'),
                               from_user=User(id=1, is_bot=False, first_name='A'), voice=VOICE)
        self.message._bot = FakeBot()

    async def test_text_is_taken_from_json_transcription(self) -> None:
        with patch.object(self.pre, '_transcribe_openai', AsyncMock(return_value='привет')):
            self.assertEqual(await self.pre._process_voice(self.message), ['[Voice transcription]: привет'])

    async def test_client_requests_default_json_format(self) -> None:
        create = AsyncMock(return_value=SimpleNamespace(text='hi'))
        audio = Path(self.dir.name) / 'a.oga'
        audio.write_bytes(b'ogg')
        with patch('openai.resources.audio.AsyncTranscriptions.create', create):
            self.assertEqual(await self.pre._transcribe_openai(str(audio)), 'hi')
        self.assertNotIn('response_format', create.await_args.kwargs)

    async def test_api_error_becomes_marker_instead_of_raising(self) -> None:
        with patch.object(self.pre, '_transcribe_openai', AsyncMock(side_effect=RuntimeError('400 bad format'))):
            result = await self.pre._process_voice(self.message)
        self.assertEqual(result, ['[Voice transcription error: 400 bad format]'])


if __name__ == '__main__':
    unittest.main()
