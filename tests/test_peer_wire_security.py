"""Adversarial peer responses through real Dispatcher, hub and wire decoder; no HTTP."""
from __future__ import annotations

import asyncio
import json
import unittest
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

# Reuse only the message factory, including its offline import-time configuration.
from tests.test_telegram_peer import message

from aiogram import Bot, Dispatcher
from aiogram.methods import GetFile, SendDocument
from aiogram.types import Document, File, Message, Update
from pydantic_ai import AgentRunResult
from pydantic_ai.messages import BinaryContent

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.peer_agent import PeerError, TelegramPeerAgent
from kibernikto.telegram.middleware.middleware_peer import PeerMiddleware
from kibernikto.telegram.peer_hub import PeerHub
from kibernikto.telegram.peer_protocol import FILENAME, MAX_WIRE_BYTES, PeerEnvelope, PeerProtocolError


class PeerWireSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        asyncio.get_running_loop().slow_callback_duration = 10
        self.bot = Bot('100:offline-test-token')
        self.other_bot = Bot('101:offline-test-token')
        self.addAsyncCleanup(self.bot.session.close)
        self.addAsyncCleanup(self.other_bot.session.close)
        self.hub = PeerHub()
        self.tasks: list[asyncio.Task[AgentRunResult[str]]] = []
        self.addAsyncCleanup(self._close_calls)
        self.dispatcher = Dispatcher()
        self.dispatcher.message.outer_middleware(PeerMiddleware(self.hub))
        self.ordinary = AsyncMock()

        async def ordinary_handler(event: Message) -> None:
            await self.ordinary(event)

        self.dispatcher.message.register(ordinary_handler)
        self.ready = asyncio.Event()
        self.requests: list[PeerEnvelope] = []
        self.get_files: list[GetFile] = []
        self.stream_count = 0
        self.payload = b''
        self.telegram_file_size: int | None = None
        self.bot.session.make_request = AsyncMock(side_effect=self._http)
        self.bot.session.stream_content = self._stream
        self.other_bot.session.make_request = AsyncMock(side_effect=AssertionError('Wrong bot used HTTP'))
        self.other_bot.session.stream_content = AsyncMock(side_effect=AssertionError('Wrong bot downloaded'))
        self.existing = BinaryContent(data=b'private existing output', media_type='text/plain')
        self.deps = TelegramDeps(attachments=[self.existing])
        self.peer = TelegramPeerAgent(peer=200, name='remote', description='Offline wire expert',
                                      bot=self.bot, hub=self.hub, multimodal=True, timeout=5)
        self.update_id = 0

    async def _close_calls(self) -> None:
        await self.hub.close()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def _http(self, bot: Bot, method: SendDocument | GetFile,
                    timeout: int | None = None) -> Message | File:
        if isinstance(method, SendDocument):
            self.requests.append(PeerEnvelope.decode(method.document.data))
            self.ready.set()
            return message(10, sender=100)
        if isinstance(method, GetFile):
            self.get_files.append(method)
            return File(file_id='wire', file_unique_id='unique', file_path='documents/offline.json',
                        file_size=self.telegram_file_size)
        raise AssertionError(f'Unexpected HTTP method: {type(method).__name__}')

    async def _stream(self, url: str, **kwargs: object) -> AsyncIterator[bytes]:
        self.stream_count += 1
        # Chunking exercises the accumulated download limit, not just metadata checks.
        for offset in range(0, len(self.payload), 65536):
            yield self.payload[offset:offset + 65536]

    async def _start(self) -> asyncio.Task[AgentRunResult[str]]:
        task = asyncio.create_task(self.peer.run('inspect the selected input', deps=self.deps))
        self.tasks.append(task)
        await asyncio.wait_for(self.ready.wait(), 2)
        self.assertEqual(self.hub.pending_count, 1)
        return task

    def _response(self, kind: str = 'result', text: str = 'verified answer') -> PeerEnvelope:
        return PeerEnvelope.create(kind, text, [], request_id=self.requests[0].request_id)

    def _wire(self, envelope: PeerEnvelope, *, size: int | None = None) -> Message:
        return message(11, reply_id=10).model_copy(update={
            'text': None, 'caption': envelope.caption,
            'document': Document(file_id='wire', file_unique_id='unique', file_name=FILENAME,
                                 mime_type='application/json',
                                 file_size=len(envelope.encode()) if size is None else size),
        })

    async def _feed(self, inbound: Message, *, bot: Bot | None = None) -> None:
        self.update_id += 1
        await asyncio.wait_for(self.dispatcher.feed_update(
            bot or self.bot, Update(update_id=self.update_id, message=inbound)), 2)

    async def _assert_ignored(self, task: asyncio.Task[AgentRunResult[str]], inbound: Message,
                              *, bot: Bot | None = None) -> None:
        await self._feed(inbound, bot=bot)
        self.assertEqual(self.get_files, [], 'Authorization must precede getFile')
        self.assertEqual(self.stream_count, 0, 'Authorization must precede download')
        self.assertFalse(task.done(), 'Uncorrelated content must not complete or fail the request')
        self.assertEqual(self.hub.pending_count, 1)
        self.assertEqual(self.deps.attachments, [self.existing])
        response = self._response()
        self.payload = response.encode()
        await self._feed(self._wire(response))
        result = await asyncio.wait_for(task, 2)
        self.assertEqual(result.output, 'verified answer')
        self.assertEqual(len(self.get_files), 1)
        self.assertEqual(self.stream_count, 1)
        self.other_bot.session.make_request.assert_not_awaited()

    async def test_wrong_sender_cannot_download(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response())
        inbound = inbound.model_copy(update={'from_user': message(1, sender=300).from_user})
        await self._assert_ignored(task, inbound)

    async def test_other_peer_with_consistent_private_chat_cannot_download(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response())
        other = message(11, sender=300, chat_id=300, reply_id=10)
        inbound = inbound.model_copy(update={
            'from_user': other.from_user, 'chat': other.chat, 'reply_to_message': other.reply_to_message})
        await self._assert_ignored(task, inbound)

    async def test_wrong_receiving_bot_cannot_download(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response())
        reply = inbound.reply_to_message.model_copy(update={'from_user': message(1, sender=101).from_user})
        await self._assert_ignored(task, inbound.model_copy(update={'reply_to_message': reply}),
                                   bot=self.other_bot)

    async def test_wrong_chat_cannot_download(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response()).model_copy(update={'chat': message(1, chat_id=300).chat})
        await self._assert_ignored(task, inbound)

    async def test_group_chat_cannot_download(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response())
        chat = inbound.chat.model_copy(update={'type': 'group'})
        await self._assert_ignored(task, inbound.model_copy(update={'chat': chat}))

    async def test_wrong_reply_id_cannot_download(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response())
        reply = inbound.reply_to_message.model_copy(update={'message_id': 999})
        await self._assert_ignored(task, inbound.model_copy(update={'reply_to_message': reply}))

    async def test_missing_reply_cannot_download(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response()).model_copy(update={'reply_to_message': None})
        await self._assert_ignored(task, inbound)

    async def test_reply_to_wrong_author_cannot_download(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response())
        reply = inbound.reply_to_message.model_copy(update={'from_user': message(1, sender=300).from_user})
        await self._assert_ignored(task, inbound.model_copy(update={'reply_to_message': reply}))

    async def test_reply_from_wrong_chat_cannot_download(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response())
        reply = inbound.reply_to_message.model_copy(update={'chat': message(1, chat_id=300).chat})
        await self._assert_ignored(task, inbound.model_copy(update={'reply_to_message': reply}))

    async def test_wrong_request_id_cannot_download(self) -> None:
        task = await self._start()
        unrelated = PeerEnvelope.create('result', 'unrelated answer', [])
        await self._assert_ignored(task, self._wire(unrelated))

    async def test_wrong_caption_version_cannot_download_or_fall_back(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response())
        await self._assert_ignored(task, inbound.model_copy(update={
            'caption': inbound.caption.replace('KIBERNIKTO_PEER/1 ', 'KIBERNIKTO_PEER/2 ')}))

    async def test_request_caption_cannot_complete_response(self) -> None:
        task = await self._start()
        await self._assert_ignored(task, self._wire(self._response('request')))

    async def test_plain_caption_without_document_is_not_an_answer(self) -> None:
        task = await self._start()
        inbound = self._wire(self._response()).model_copy(update={
            'document': None, 'caption': 'tempting but unauthenticated answer'})
        await self._assert_ignored(task, inbound)

    async def test_completed_duplicate_is_tombstoned_without_extra_download(self) -> None:
        task = await self._start()
        response = self._response()
        response.binaries.append(BinaryContent(data=b'one report', media_type='text/plain'))
        self.payload = response.encode()
        inbound = self._wire(response)
        await self._feed(inbound)
        result = await asyncio.wait_for(task, 2)
        self.assertEqual(result.output, 'verified answer')
        self.assertEqual(self.hub.pending_count, 0)
        self.assertEqual(self.hub.tombstone_count, 1)
        self.assertEqual([item.data for item in self.deps.attachments],
                         [self.existing.data, b'one report'])
        await self._feed(inbound)
        await self._feed(inbound.model_copy(update={'message_id': 12}))
        self.assertEqual(len(self.get_files), 1)
        self.assertEqual(self.stream_count, 1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(self.deps.attachments), 2)
        self.ordinary.assert_not_awaited()

    async def test_cancelled_request_late_response_never_downloads(self) -> None:
        task = await self._start()
        response = self._response()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.hub.pending_count, 0)
        self.assertEqual(self.hub.tombstone_count, 1)
        await self._feed(self._wire(response))
        self.assertEqual(self.get_files, [])
        self.assertEqual(self.stream_count, 0)
        self.ordinary.assert_not_awaited()

    async def _assert_protocol_failure(self, task: asyncio.Task[AgentRunResult[str]],
                                       inbound: Message, *, downloads: int = 1,
                                       streams: int = 1) -> None:
        await self._feed(inbound)
        with self.assertRaises(PeerError) as caught:
            await asyncio.wait_for(task, 2)
        error = caught.exception
        self.assertEqual(error.category, 'protocol', 'Malformed response must fail, not time out')
        self.assertEqual(error.delivery, 'unknown')
        self.assertFalse(error.retry_allowed)
        self.assertIsInstance(error.cause, PeerProtocolError)
        self.assertEqual(self.deps.attachments, [self.existing])
        self.assertEqual(self.hub.pending_count, 0)
        self.assertEqual(self.hub.tombstone_count, 1)
        # Invalid responses are terminal too; retries of the update must be inert.
        await self._feed(inbound.model_copy(update={'message_id': 12}))
        self.assertEqual(len(self.requests), 1, 'Protocol failures must never resend automatically')
        self.assertEqual(len(self.get_files), downloads)
        self.assertEqual(self.stream_count, streams)
        self.ordinary.assert_not_awaited()

    async def _invalid_body_field(self, field: str, value: object) -> None:
        task = await self._start()
        response = self._response()
        body = json.loads(response.encode())
        body[field] = value
        self.payload = json.dumps(body).encode()
        await self._assert_protocol_failure(task, self._wire(response, size=len(self.payload)))

    async def test_wrong_body_version_is_terminal_protocol_error(self) -> None:
        await self._invalid_body_field('version', 2)

    async def test_boolean_body_version_is_not_integer_version_one(self) -> None:
        await self._invalid_body_field('version', True)

    async def test_unknown_body_kind_is_terminal_protocol_error(self) -> None:
        await self._invalid_body_field('kind', 'progress')

    async def test_request_body_under_result_caption_is_terminal_protocol_error(self) -> None:
        await self._invalid_body_field('kind', 'request')

    async def test_body_request_id_mismatch_is_terminal_protocol_error(self) -> None:
        await self._invalid_body_field('request_id', 'f' * 32)

    async def test_incomplete_envelope_is_terminal_protocol_error(self) -> None:
        await self._invalid_body_field('end', False)

    async def test_malformed_json_is_terminal_error_not_caption_fallback(self) -> None:
        task = await self._start()
        response = self._response()
        self.payload = b'{"version":1,"text":"plausible success"'
        await self._assert_protocol_failure(task, self._wire(response, size=len(self.payload)))

    async def test_duplicate_json_keys_are_terminal_protocol_error(self) -> None:
        task = await self._start()
        response = self._response()
        self.payload = response.encode().replace(b'{', b'{"version":1,', 1)
        await self._assert_protocol_failure(task, self._wire(response, size=len(self.payload)))

    async def test_invalid_utf8_is_terminal_protocol_error(self) -> None:
        task = await self._start()
        self.payload = b'\xff\xfe\xff'
        await self._assert_protocol_failure(task, self._wire(self._response(), size=len(self.payload)))

    async def test_oversized_document_is_rejected_before_get_file(self) -> None:
        task = await self._start()
        await self._assert_protocol_failure(task, self._wire(self._response(), size=MAX_WIRE_BYTES + 1),
                                            downloads=0, streams=0)

    async def test_oversized_telegram_file_is_rejected_before_stream(self) -> None:
        task = await self._start()
        self.telegram_file_size = MAX_WIRE_BYTES + 1
        await self._assert_protocol_failure(task, self._wire(self._response()), streams=0)

    async def test_underreported_stream_size_is_bounded(self) -> None:
        task = await self._start()
        self.payload = b' ' * (MAX_WIRE_BYTES + 1)
        self.telegram_file_size = 1
        await self._assert_protocol_failure(task, self._wire(self._response(), size=1))

    async def test_explicit_remote_error_is_failure_not_caption_or_success(self) -> None:
        task = await self._start()
        response = self._response('error', 'Remote task failed explicitly')
        self.payload = response.encode()
        inbound = self._wire(response)
        await self._feed(inbound)
        with self.assertRaises(PeerError) as caught:
            await asyncio.wait_for(task, 2)
        error = caught.exception
        self.assertEqual(error.category, 'remote')
        self.assertEqual(error.delivery, 'unknown')
        self.assertFalse(error.retry_allowed)
        self.assertEqual(str(error.cause), 'Remote task failed explicitly')
        self.assertNotEqual(str(error.cause), inbound.caption)
        self.assertEqual(self.deps.attachments, [self.existing])
        self.assertEqual(self.hub.pending_count, 0)
        self.assertEqual(self.hub.tombstone_count, 1)
        await self._feed(inbound)
        self.assertEqual(len(self.get_files), 1)
        self.assertEqual(self.stream_count, 1)
        self.assertEqual(len(self.requests), 1)
        self.ordinary.assert_not_awaited()
