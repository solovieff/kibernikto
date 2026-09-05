"""Actual PydanticAI + Dispatcher with only Telegram HTTP doubled."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from tests.test_telegram_peer import message
from aiogram import Bot, Dispatcher
from aiogram.methods import SendDocument, GetFile
from aiogram.types import Document, File, Update
from pydantic_ai.messages import BinaryContent, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai_harness.subagents import SubAgent, SubAgents
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
from kibernikto.telegram.agent.telegram_app import TelegramApp
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.peer_protocol import PeerEnvelope, FILENAME


def wire_message(envelope, *, sender=200, reply_id=10, message_id=11):
    return message(message_id, sender=sender, reply_id=reply_id).model_copy(update={
        'text': None, 'caption': envelope.caption,
        'document': Document(file_id='wire', file_unique_id='unique', file_name=FILENAME,
                             mime_type='application/json', file_size=len(envelope.encode()))})


class MultimodalTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_dispatcher_runs_image_model_and_returns_named_tool_bytes(self):
        bot = Bot('200:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        photo = BinaryContent(data=b'photo', media_type='image/png')
        audio = BinaryContent(data=b'audio', media_type='audio/wav', vendor_metadata={'filename': 'tone.wav'})
        request = PeerEnvelope.create('request', 'describe', [photo, audio])
        inbound = wire_message(request, sender=100, reply_id=None).model_copy(update={
            'chat': message(1, chat_id=100).chat})
        sent = []
        async def http(bot, method, timeout=None):
            if isinstance(method, GetFile):
                return File(file_id='wire', file_unique_id='unique', file_path='documents/wire.json')
            if isinstance(method, SendDocument):
                sent.append(method)
                return message(12, sender=200)
            self.fail(type(method).__name__)
        async def stream(url, **kwargs):
            yield request.encode()
        bot.session.make_request = AsyncMock(side_effect=http)
        bot.session.stream_content = stream
        observed = []
        def model(messages, info):
            prompt = next(p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart))
            observed.extend(prompt)
            return ModelResponse(parts=[TextPart('red circle')])
        remote = TelegramAgent(model=FunctionModel(model), history_storage=None)
        deps = TelegramDeps(is_personal=True)
        remote.build_deps = AsyncMock(return_value=deps)
        async def handler(event):
            result = await remote.process_message(event)
            if result is not None:
                deps.add_attachment(BinaryContent(data=result.output.encode(), media_type='text/plain',
                                                  vendor_metadata={'filename': 'vision.txt'}))
                # A normal tool queues these before run returns; emulate at delivery boundary.
                remote._materialize_attachments(result, deps)
            await remote.reply_to(event, result)
        app.dispatcher.message.register(handler)
        with patch.object(TELEGRAM_SETTINGS, 'PEER_IDS', [100]):
            await app.dispatcher.feed_update(bot, Update(update_id=1, message=inbound))
        self.assertEqual(observed[0], 'describe')
        self.assertEqual([p.data for p in observed if isinstance(p, BinaryContent)], [b'photo'])
        self.assertEqual([p.data for p in deps.peer_inputs], [b'photo', b'audio'])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].reply_parameters.message_id, inbound.message_id)
        response = PeerEnvelope.decode(sent[0].document.data)
        self.assertEqual(response.kind, 'result')
        self.assertEqual(response.request_id, request.request_id)
        self.assertEqual(response.text, 'red circle')
        self.assertEqual(response.binaries[0].data, b'red circle')
        self.assertEqual(response.binaries[0].vendor_metadata['filename'], 'vision.txt')

    async def test_capture_mode_keeps_current_bytes_without_legacy_processing(self):
        from aiogram.types import PhotoSize
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        human = message(1, sender=300, chat_id=300).model_copy(update={
            'from_user': message(1).from_user.model_copy(update={'id': 300, 'is_bot': False}),
            'text': None, 'caption': 'describe',
            'photo': [PhotoSize(file_id='photo', file_unique_id='u', width=1, height=1, file_size=5)]}).as_(bot)
        photo = BinaryContent(data=b'photo', media_type='image/jpeg')
        agent = TelegramAgent(model=FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart('done')])),
                              history_storage=None, capture_peer_media=True)
        deps = TelegramDeps()
        agent.build_deps = AsyncMock(return_value=deps)
        agent.pre_processor.process_tg_message = AsyncMock(side_effect=AssertionError('legacy processing'))
        with patch('kibernikto.telegram.peer_inputs.capture_peer_inputs', new=AsyncMock(return_value=[photo])) as capture:
            result = await agent.process_message(human)
        self.assertEqual(result.output, 'done')
        self.assertEqual(deps.peer_inputs, [photo])
        self.assertEqual(deps.user_message_parts, ['describe', photo])
        capture.assert_awaited_once_with(human)

    async def test_inbound_request_dedup_precedes_download_and_edits_are_inert(self):
        bot = Bot('200:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        envelope = PeerEnvelope.create('request', 'task', [])
        inbound = wire_message(envelope, sender=100, reply_id=None).model_copy(update={
            'chat': message(1, chat_id=100).chat}).as_(bot)
        calls = []
        def model(messages, info):
            calls.append(messages)
            return ModelResponse(parts=[TextPart('done')])
        agent = TelegramAgent(model=FunctionModel(model), history_storage=None)
        agent.build_deps = AsyncMock(return_value=TelegramDeps())
        with patch.object(TELEGRAM_SETTINGS, 'PEER_IDS', [100]), patch(
                'kibernikto.ai.agent.telegram.telegram_agent.download_envelope', new=AsyncMock(return_value=envelope)) as download:
            self.assertIsNotNone(await agent.process_message(inbound))
            self.assertIsNone(await agent.process_message(inbound))
            self.assertIsNone(await agent.process_message(inbound.model_copy(update={'message_id': 99})))
            edited = inbound.model_copy(update={'edit_date': inbound.date, 'caption': envelope.caption.replace(envelope.request_id, 'f' * 32)})
            self.assertIsNone(await agent.process_message(edited))
            download.assert_awaited_once()
        self.assertEqual(len(calls), 1)

    async def test_invalid_inbound_body_returns_bounded_explicit_error(self):
        from kibernikto.telegram.peer_protocol import PeerProtocolError
        bot = Bot('200:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        request = PeerEnvelope.create('request', 'task', [])
        inbound = wire_message(request, sender=100, reply_id=None).model_copy(update={
            'chat': message(1, chat_id=100).chat}).as_(bot)
        agent = TelegramAgent(model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart('done')])), history_storage=None)
        agent.build_deps = AsyncMock()
        with patch.object(TELEGRAM_SETTINGS, 'PEER_IDS', [100]), patch(
                'kibernikto.ai.agent.telegram.telegram_agent.download_envelope', new=AsyncMock(side_effect=PeerProtocolError('invalid'))):
            result = await agent.process_message(inbound)
        self.assertIsInstance(result, PeerEnvelope)
        self.assertEqual(result.kind, 'error')
        self.assertEqual(result.request_id, request.request_id)
        agent.build_deps.assert_not_awaited()

    async def test_unsolicited_wire_request_still_passes_firewall_before_download(self):
        from kibernikto.telegram.middleware.middleware_firewall import FirewallMiddleware
        bot = Bot('200:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        app.dispatcher.message.outer_middleware(FirewallMiddleware())
        envelope = PeerEnvelope.create('request', 'task', [])
        inbound = wire_message(envelope, sender=100, reply_id=None).model_copy(update={
            'chat': message(1, chat_id=100).chat})
        agent = TelegramAgent(model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart('done')])), history_storage=None)
        async def handler(event):
            await agent.process_message(event)
        app.dispatcher.message.register(handler)
        bot.session.make_request = AsyncMock(return_value=message(12))
        with patch.multiple(TELEGRAM_SETTINGS, PEER_IDS=[100], PUBLIC=False, MASTER_ID=999, MASTER_IDS=[]), patch(
                'kibernikto.ai.agent.telegram.telegram_agent.download_envelope', new=AsyncMock()) as download, self.assertLogs(
                    'kibernikto.telegram.middleware.middleware_firewall', level='WARNING'):
            await app.dispatcher.feed_update(bot, Update(update_id=1, message=inbound))
            download.assert_not_awaited()

    async def test_remote_model_failure_sends_error_envelope(self):
        bot = Bot('200:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        envelope = PeerEnvelope.create('request', 'task', [])
        inbound = wire_message(envelope, sender=100, reply_id=None).model_copy(update={
            'chat': message(1, chat_id=100).chat}).as_(bot)
        def fail(messages, info):
            raise RuntimeError('private internal details')
        agent = TelegramAgent(model=FunctionModel(fail), history_storage=None)
        agent.build_deps = AsyncMock(return_value=TelegramDeps())
        bot.session.make_request = AsyncMock(return_value=message(12, sender=200))
        with patch.object(TELEGRAM_SETTINGS, 'PEER_IDS', [100]), patch(
                'kibernikto.ai.agent.telegram.telegram_agent.download_envelope', new=AsyncMock(return_value=envelope)), self.assertLogs(
                    'kibernikto.ai.agent.telegram.telegram_agent', level='ERROR'):
            result = await agent.process_message(inbound)
            await agent.reply_to(inbound, result)
        sent = bot.session.make_request.await_args.args[1]
        self.assertIsInstance(sent, SendDocument)
        response = PeerEnvelope.decode(sent.document.data)
        self.assertEqual(response.kind, 'error')
        self.assertEqual(response.request_id, envelope.request_id)
        self.assertNotIn('private internal', response.text)
        self.assertEqual(response.binaries, [])

    async def test_remote_error_is_terminal_and_empty_result_completes(self):
        from kibernikto.ai.agent.telegram.peer_agent import PeerError
        for kind in ('error', 'result'):
            bot = Bot('100:offline-test-token')
            self.addAsyncCleanup(bot.session.close)
            app = TelegramApp(bot, Dispatcher())
            self.addAsyncCleanup(app.peer_hub.close)
            ready = asyncio.Event()
            outgoing = []
            async def http(bot, method, timeout=None):
                if isinstance(method, SendDocument):
                    outgoing.append(PeerEnvelope.decode(method.document.data))
                    ready.set()
                    return message(10, sender=100)
                return File(file_id='wire', file_unique_id='u', file_path='documents/wire')
            async def stream(url, **kwargs):
                yield response.encode()
            bot.session.make_request = AsyncMock(side_effect=http)
            bot.session.stream_content = stream
            peer = TelegramPeerAgent(peer=200, name='remote', description='expert', bot=bot,
                                     hub=app.peer_hub, multimodal=True, timeout=0.4)
            task = asyncio.create_task(peer.run('task'))
            await ready.wait()
            response = PeerEnvelope.create(kind, 'execution failed' if kind == 'error' else '', [],
                                           request_id=outgoing[0].request_id)
            await app.dispatcher.feed_update(bot, Update(update_id=1, message=wire_message(response)))
            if kind == 'error':
                with self.assertRaises(PeerError) as caught:
                    await task
                self.assertEqual(caught.exception.category, 'remote')
            else:
                result = await task
                self.assertEqual(result.output, '')

    async def test_shutdown_cancels_active_download_and_duplicate_cannot_download_twice(self):
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        ready, downloading, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()
        outgoing = []
        async def http(bot, method, timeout=None):
            if isinstance(method, SendDocument):
                outgoing.append(PeerEnvelope.decode(method.document.data))
                ready.set()
                return message(10, sender=100)
            return File(file_id='wire', file_unique_id='u', file_path='documents/wire')
        async def stream(url, **kwargs):
            downloading.set()
            try:
                await asyncio.Event().wait()
                yield b''
            finally:
                cleaned.set()
        bot.session.make_request = AsyncMock(side_effect=http)
        bot.session.stream_content = stream
        peer = TelegramPeerAgent(peer=200, name='remote', description='expert', bot=bot, hub=app.peer_hub,
                                 multimodal=True)
        task = asyncio.create_task(peer.run('task'))
        await ready.wait()
        response = PeerEnvelope.create('result', 'answer', [], request_id=outgoing[0].request_id)
        incoming = asyncio.create_task(app.dispatcher.feed_update(bot, Update(update_id=1, message=wire_message(response))))
        await downloading.wait()
        await app.dispatcher.feed_update(bot, Update(update_id=2, message=wire_message(response)))
        self.assertEqual(bot.session.make_request.await_count, 2)
        await app.peer_hub.close()
        self.assertTrue(task.cancelled())
        self.assertTrue(cleaned.is_set())
        await asyncio.wait_for(incoming, 1)
        self.assertEqual(app.peer_hub.pending_count, 0)

    async def test_oversized_remote_output_sends_error_not_partial_result(self):
        from pydantic_ai.models.test import TestModel
        from kibernikto.telegram.peer_protocol import MAX_BINARY_BYTES
        bot = Bot('200:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        request = PeerEnvelope.create('request', 'task', [])
        incoming = wire_message(request, sender=100, reply_id=None).model_copy(update={
            'chat': message(1, chat_id=100).chat}).as_(bot)
        remote = TelegramAgent(model=TestModel(custom_output_text='done'), history_storage=None)
        deps = TelegramDeps(attachments=[BinaryContent(data=b'x' * (MAX_BINARY_BYTES + 1), media_type='text/plain')])
        result = await remote.run('task', deps=deps)
        result._peer_request_id = request.request_id
        bot.session.make_request = AsyncMock(return_value=message(12))
        with patch.object(TELEGRAM_SETTINGS, 'PEER_IDS', [100]):
            await remote.reply_to(incoming, result)
        sent = bot.session.make_request.await_args.args[1]
        self.assertEqual(PeerEnvelope.decode(sent.document.data).kind, 'error')
        self.assertEqual(bot.session.make_request.await_count, 1)

    async def test_multimodal_upload_timeout_and_shutdown_cleanup(self):
        from kibernikto.ai.agent.telegram.peer_agent import PeerError
        for shutdown in (False, True):
            bot = Bot('100:offline-test-token')
            self.addAsyncCleanup(bot.session.close)
            app = TelegramApp(bot, Dispatcher())
            self.addAsyncCleanup(app.peer_hub.close)
            started, cleaned = asyncio.Event(), asyncio.Event()
            async def http(bot, method, timeout=None):
                self.assertIsInstance(method, SendDocument)
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()
            bot.session.make_request = AsyncMock(side_effect=http)
            peer = TelegramPeerAgent(peer=200, name='remote', description='expert', bot=bot,
                                     hub=app.peer_hub, multimodal=True, timeout=0.1 if not shutdown else 3)
            task = asyncio.create_task(peer.run('task'))
            await started.wait()
            if shutdown:
                await app.peer_hub.close()
                self.assertTrue(task.cancelled())
            else:
                with self.assertRaises(PeerError) as caught:
                    await task
                self.assertEqual(caught.exception.category, 'timeout')
                self.assertEqual(caught.exception.delivery, 'unknown')
            self.assertTrue(cleaned.is_set())
            self.assertEqual(app.peer_hub.pending_count, 0)
            self.assertEqual(bot.session.make_request.await_count, 1)

    async def test_correlated_bad_envelope_is_failed_tool_not_caption_or_timeout(self):
        from kibernikto.ai.agent.telegram.peer_agent import PeerError
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        ready = asyncio.Event()
        sent = []
        async def http(bot, method, timeout=None):
            if isinstance(method, SendDocument):
                sent.append(PeerEnvelope.decode(method.document.data))
                ready.set()
                return message(10, sender=100)
            if isinstance(method, GetFile):
                return File(file_id='wire', file_unique_id='u', file_path='documents/wire')
            self.fail(type(method).__name__)
        async def stream(url, **kwargs):
            yield b'{"end":false}'
        bot.session.make_request = AsyncMock(side_effect=http)
        bot.session.stream_content = stream
        peer = TelegramPeerAgent(peer=200, name='remote', description='expert', bot=bot, hub=app.peer_hub,
                                 multimodal=True, timeout=2)
        task = asyncio.create_task(peer.run('task'))
        await asyncio.wait_for(ready.wait(), 1)
        envelope = PeerEnvelope.create('result', 'not a result', [], request_id=sent[0].request_id)
        await app.dispatcher.feed_update(bot, Update(update_id=1, message=wire_message(envelope)))
        with self.assertRaises(PeerError) as caught:
            await task
        self.assertEqual(caught.exception.category, 'protocol')
        self.assertEqual(caught.exception.delivery, 'unknown')
        self.assertFalse(caught.exception.retry_allowed)
        self.assertEqual(app.peer_hub.pending_count, 0)

    async def test_wrong_correlation_and_progress_never_download_or_complete(self):
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        ready = asyncio.Event()
        requests = []
        async def http(bot, method, timeout=None):
            if isinstance(method, SendDocument):
                requests.append(PeerEnvelope.decode(method.document.data))
                ready.set()
                return message(10, sender=100)
            self.fail('Unauthenticated download')
        bot.session.make_request = AsyncMock(side_effect=http)
        peer = TelegramPeerAgent(peer=200, name='remote', description='expert', bot=bot, hub=app.peer_hub,
                                 multimodal=True)
        task = asyncio.create_task(peer.run('task'))
        await asyncio.wait_for(ready.wait(), 1)
        envelope = PeerEnvelope.create('result', 'answer', [], request_id=requests[0].request_id)
        correct = wire_message(envelope)
        for index, inbound in enumerate([wire_message(envelope, sender=300), wire_message(envelope, reply_id=999),
                wire_message(envelope, reply_id=None), message(11, reply_id=10, text='working'),
                wire_message(PeerEnvelope.create('result', 'wrong id', [])),
                correct.model_copy(update={'chat': message(1, chat_id=300).chat})]):
            await app.dispatcher.feed_update(bot, Update(update_id=index, message=inbound))
            self.assertFalse(task.done())
        await app.dispatcher.feed_update(bot, Update(update_id=20, edited_message=correct))
        self.assertFalse(task.done())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await app.dispatcher.feed_update(bot, Update(update_id=21, message=correct))
        self.assertEqual(bot.session.make_request.await_count, 1)

    async def test_subagent_sends_only_selected_task_bytes_and_collects_atomic_result(self):
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        ready = asyncio.Event()
        requests = []
        answer = None
        async def http(bot, method, timeout=None):
            if isinstance(method, SendDocument):
                requests.append(PeerEnvelope.decode(method.document.data))
                ready.set()
                return message(10, sender=100)
            if isinstance(method, GetFile):
                return File(file_id='wire', file_unique_id='unique', file_path='documents/wire.json', file_size=len(answer.encode()))
            self.fail(type(method).__name__)
        async def stream(url, **kwargs):
            yield answer.encode()
        bot.session.make_request = AsyncMock(side_effect=http)
        bot.session.stream_content = stream
        peer = TelegramPeerAgent(peer=200, name='remote', description='vision expert',
                                 bot=bot, hub=app.peer_hub, multimodal=True)
        def parent_model(messages, info):
            returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
            if returns:
                self.assertEqual(returns[-1].content, 'saw shapes')
                return ModelResponse(parts=[TextPart('done')])
            return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'remote', 'task': 'describe only this'})])
        parent = KiberniktoAgent(model=FunctionModel(parent_model), history_storage=None,
                                capabilities=[SubAgents(agents=[SubAgent(peer)])])
        photo = BinaryContent(data=b'photo', media_type='image/png')
        unrelated = BinaryContent(data=b'private output', media_type='text/plain')
        deps = TelegramDeps(user_message_parts=['do not forward my full text'], attachments=[unrelated], peer_inputs=[photo])
        task = asyncio.create_task(parent.run('private parent instruction', deps=deps))
        await asyncio.wait_for(ready.wait(), 3)
        self.assertEqual(requests[0].text, 'describe only this')
        self.assertEqual([p.data for p in requests[0].binaries], [b'photo'])
        answer = PeerEnvelope.create('result', 'saw shapes', [BinaryContent(data=b'report', media_type='text/plain',
                                      vendor_metadata={'filename': 'report.txt'})], request_id=requests[0].request_id)
        await app.dispatcher.feed_update(bot, Update(update_id=1, message=wire_message(answer)))
        result = await asyncio.wait_for(task, 3)
        self.assertEqual(result.output, 'done')
        self.assertEqual([p.data for p in deps.attachments], [b'private output', b'report'])
        self.assertEqual([p.data for p in result.response.files], [b'private output', b'report'])
        self.assertEqual(app.peer_hub.pending_count, 0)
