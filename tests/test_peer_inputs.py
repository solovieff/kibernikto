"""Offline transport-original capture tests using real aiogram messages."""
import io
import unittest
from datetime import datetime, timezone

from aiogram.types import Chat, File, Message, PhotoSize


class FakeBot:
    def __init__(self, payloads: dict[str, bytes], file_sizes: dict[str, int | None] | None = None):
        self.payloads = payloads
        self.file_sizes = file_sizes or {}
        self.lookups: list[str] = []
        self.downloads: list[str] = []
        self.destinations: list[io.BytesIO] = []
        self.written = 0

    async def get_file(self, file_id: str) -> File:
        self.lookups.append(file_id)
        return File(file_id=file_id, file_unique_id=file_id,
                    file_path=file_id, file_size=self.file_sizes.get(file_id))

    async def download_file(self, file_path: str, destination: io.BytesIO,
                            **kwargs: object) -> io.BytesIO:
        self.downloads.append(file_path)
        self.destinations.append(destination)
        payload = self.payloads[file_path]
        for start in range(0, len(payload), 65536):
            self.written += destination.write(payload[start:start + 65536])
        destination.seek(0)
        return destination


def message(bot: FakeBot, **fields: object) -> Message:
    return Message(message_id=7, date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                   chat=Chat(id=1, type='private'), **fields).as_(bot)


def photo(file_id: str, size: int | None = None) -> PhotoSize:
    return PhotoSize(file_id=file_id, file_unique_id=file_id,
                     width=10, height=10, file_size=size)


class PeerInputsTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_errors_and_cancellation_propagate_and_close_buffer(self):
        import asyncio
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        for failure in (OSError('download failed'), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__):
                class FailingBot(FakeBot):
                    async def download_file(self, file_path: str, destination: io.BytesIO,
                                            **kwargs: object) -> io.BytesIO:
                        self.destinations.append(destination)
                        destination.write(b'partial')
                        raise failure

                bot = FailingBot({})
                with self.assertRaises(type(failure)) as caught:
                    await capture_peer_inputs(message(bot, photo=[photo('photo')]))
                self.assertIs(caught.exception, failure)
                self.assertTrue(bot.destinations[0].closed)

    async def test_part_limit_is_checked_before_any_download(self):
        from unittest.mock import patch
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        from kibernikto.telegram.peer_protocol import PeerProtocolError
        bot = FakeBot({'photo': b'x', 'doc': b'y'})
        current = message(bot, photo=[photo('photo')], document={
            'file_id': 'doc', 'file_unique_id': 'doc'})
        with patch('kibernikto.telegram.peer_inputs.MAX_PARTS', 1, create=True):
            with self.assertRaises(PeerProtocolError):
                await capture_peer_inputs(current)
        self.assertEqual(bot.lookups, [])
        self.assertEqual(bot.downloads, [])

    async def test_missing_telegram_file_path_is_explicit_error(self):
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        from kibernikto.telegram.peer_protocol import PeerProtocolError

        class MissingPathBot(FakeBot):
            async def get_file(self, file_id: str) -> File:
                return File(file_id=file_id, file_unique_id=file_id)

        bot = MissingPathBot({'photo': b'bytes'})
        with self.assertRaisesRegex(PeerProtocolError, 'path'):
            await capture_peer_inputs(message(bot, photo=[photo('photo')]))
        self.assertEqual(bot.downloads, [])

    async def test_aggregate_limit_counts_previous_actual_downloads(self):
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        from kibernikto.telegram.peer_protocol import MAX_BINARY_BYTES, PeerProtocolError
        for second_size in (None, 2):
            with self.subTest(second_size=second_size):
                bot = FakeBot({'photo': b'x' * (MAX_BINARY_BYTES - 1), 'doc': b'yy'},
                              {'doc': second_size})
                current = message(bot, photo=[photo('photo')], document={
                    'file_id': 'doc', 'file_unique_id': 'doc'})
                with self.assertRaises(PeerProtocolError):
                    await capture_peer_inputs(current)
                self.assertLessEqual(bot.written, MAX_BINARY_BYTES)
                self.assertEqual(bot.downloads, ['photo', 'doc'] if second_size is None else ['photo'])
                self.assertTrue(all(d.closed for d in bot.destinations))

    async def test_stream_enforces_real_size_with_missing_or_lying_metadata(self):
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        from kibernikto.telegram.peer_protocol import MAX_BINARY_BYTES, PeerProtocolError
        for size in (None, 0, 1, MAX_BINARY_BYTES):
            with self.subTest(size=size):
                bot = FakeBot({'large': b'x' * (MAX_BINARY_BYTES + 1)}, {'large': size})
                with self.assertRaises(PeerProtocolError):
                    await capture_peer_inputs(message(bot, photo=[photo('large', size)]))
                self.assertEqual(bot.downloads, ['large'])
                self.assertLessEqual(bot.written, MAX_BINARY_BYTES)
                self.assertTrue(bot.destinations[0].closed)

    async def test_exact_binary_limit_is_allowed_without_size_metadata(self):
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        from kibernikto.telegram.peer_protocol import MAX_BINARY_BYTES
        bot = FakeBot({'exact': b'x' * MAX_BINARY_BYTES})
        parts = await capture_peer_inputs(message(bot, photo=[photo('exact')]))
        self.assertEqual(parts[0].data, bot.payloads['exact'])

    async def test_oversized_metadata_rejected_before_download(self):
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        from kibernikto.telegram.peer_protocol import MAX_BINARY_BYTES, PeerProtocolError
        for message_size, telegram_size in ((MAX_BINARY_BYTES + 1, None),
                                             (None, MAX_BINARY_BYTES + 1),
                                             (1, MAX_BINARY_BYTES + 1)):
            with self.subTest(message_size=message_size, telegram_size=telegram_size):
                bot = FakeBot({'large': b'small'}, {'large': telegram_size})
                with self.assertRaises(PeerProtocolError):
                    await capture_peer_inputs(message(bot, photo=[photo('large', message_size)]))
                self.assertEqual(bot.downloads, [])

    async def test_photo_uses_last_size_and_preserves_original_bytes(self):
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        bot = FakeBot({'large': b'\xff\xd8original-jpeg'})
        current = message(bot, photo=[photo('small'), photo('large')], caption='not binary')

        parts = await capture_peer_inputs(current)

        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].data, b'\xff\xd8original-jpeg')
        self.assertEqual(parts[0].media_type, 'image/jpeg')
        self.assertEqual(parts[0].vendor_metadata, {'filename': 'photo.jpg'})
        self.assertEqual(bot.lookups, ['large'])
        self.assertEqual(bot.downloads, ['large'])
        self.assertTrue(bot.destinations[0].closed)

    async def test_voice_audio_document_preserve_bytes_mime_and_names(self):
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        cases = [
            ('voice', {'duration': 2, 'mime_type': 'audio/opus'}, 'audio/ogg', 'voice.ogg'),
            ('audio', {'duration': 2, 'mime_type': 'audio/mpeg', 'file_name': 'café.mp3'},
             'audio/mpeg', 'café.mp3'),
            ('audio', {'duration': 2}, 'application/octet-stream', 'audio.bin'),
            ('document', {'mime_type': 'application/pdf', 'file_name': 'report.pdf'},
             'application/pdf', 'report.pdf'),
            ('document', {}, 'application/octet-stream', 'document.bin'),
        ]
        for kind, fields, mime, name in cases:
            with self.subTest(kind=kind, fields=fields):
                bot = FakeBot({'original': b'\x00raw bytes; not parsed or transcribed'})
                media = {'file_id': 'original', 'file_unique_id': 'original', **fields}
                parts = await capture_peer_inputs(message(bot, **{kind: media}))
                self.assertEqual(len(parts), 1)
                self.assertEqual(parts[0].data, bot.payloads['original'])
                self.assertEqual(parts[0].media_type, mime)
                self.assertEqual(parts[0].vendor_metadata, {'filename': name})

    async def test_text_caption_reply_history_and_unsupported_media_are_ignored(self):
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        bot = FakeBot({})
        ancestor = message(bot, photo=[photo('do-not-download')])
        current = message(bot, text='only text', caption='not bytes', reply_to_message=ancestor,
                          video={'file_id': 'video', 'file_unique_id': 'video',
                                 'width': 10, 'height': 10, 'duration': 1})
        self.assertEqual(await capture_peer_inputs(current), [])
        self.assertEqual(bot.lookups, [])
        self.assertEqual(bot.downloads, [])

    async def test_unsafe_filenames_use_fixed_fallback_not_path_basename(self):
        from kibernikto.telegram.peer_inputs import capture_peer_inputs
        from kibernikto.telegram.peer_protocol import PeerEnvelope
        for unsafe in ('../secret.pdf', '/tmp/secret', 'C:\\secret', '..', '.',
                       'bad\x00name', 'bad\nname', 'x' * 129):
            with self.subTest(filename=unsafe):
                bot = FakeBot({'doc': b'original'})
                current = message(bot, document={'file_id': 'doc', 'file_unique_id': 'doc',
                                                 'file_name': unsafe})
                parts = await capture_peer_inputs(current)
                self.assertEqual(parts[0].vendor_metadata, {'filename': 'document.bin'})
                self.assertEqual(PeerEnvelope.decode(
                    PeerEnvelope.create('request', '', parts).encode()).binaries[0].data,
                    b'original')
