"""Offline error policy through real aiogram HTTP parsing and SubAgents."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai_harness.subagents import SubAgent, SubAgents

from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
from kibernikto.telegram.peer_hub import PeerHub


class HttpResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return json.dumps(self.body)


class HttpSession:
    """Replace only the HTTP boundary, retaining aiogram's request/error handling."""
    def __init__(self, response: HttpResponse):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(url.rsplit('/', 1)[-1])
        return self.response


class PeerErrorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 10

    def peer_with_http(self, status: int, body: dict, **kwargs):
        http = HttpSession(HttpResponse(status, body))
        session = AiohttpSession()
        session.create_session = AsyncMock(return_value=http)
        bot = Bot('100:offline-test-token', session=session)
        hub = PeerHub()
        self.addAsyncCleanup(session.close)
        self.addAsyncCleanup(hub.close)
        peer = TelegramPeerAgent(peer=200, name='remote', description='Remote expert',
                                 bot=bot, hub=hub, **kwargs)
        return peer, http, hub

    async def recover(self, peer, **controls):
        def parent_model(messages, info):
            observations = [p for m in messages for p in m.parts
                            if isinstance(p, (ToolReturnPart, RetryPromptPart))]
            if observations:
                return ModelResponse(parts=[TextPart('No peer answer; ask another expert.')])
            return ModelResponse(parts=[ToolCallPart('delegate_task',
                                                     {'agent_name': 'remote', 'task': 'question'})])

        parent = Agent(FunctionModel(parent_model), capabilities=[SubAgents(
            agents=[SubAgent(peer, **controls)], contain_errors=True, tool_retries=0)])
        result = await parent.run('delegate')
        self.assertEqual(result.output, 'No peer answer; ask another expert.')
        parts = [p for m in result.all_messages() for p in m.parts]
        self.assertFalse(any(isinstance(p, RetryPromptPart) for p in parts), parts)
        returns = [p for p in parts if isinstance(p, ToolReturnPart)]
        self.assertEqual(len(returns), 1)
        self.assertEqual(returns[0].outcome, 'failed')
        return json.loads(returns[0].content)

    async def test_raw_tool_manager_propagates_peer_failure_without_a_success_result(self):
        from aiogram.exceptions import TelegramForbiddenError
        from pydantic_ai import RunContext, ToolFailed
        from pydantic_ai.models.test import TestModel
        from pydantic_ai.tool_manager import ToolManager
        from pydantic_ai.usage import RunUsage
        from kibernikto.ai.agent.telegram.peer_agent import PeerError

        for controls in ({}, {'contain_errors': False}, {'on_failure': 'NOT A PEER ANSWER'}):
            with self.subTest(controls=controls):
                peer, http, hub = self.peer_with_http(403, {
                    'ok': False, 'error_code': 403, 'description': 'Forbidden: bot was blocked by the user'})
                subagents = SubAgents(agents=[SubAgent(peer, **controls)],
                                      contain_errors=True, tool_retries=0)
                ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
                manager = await ToolManager(subagents.get_toolset()).for_run_step(ctx)
                call = ToolCallPart('delegate_task', {'agent_name': 'remote', 'task': 'question'})

                with self.assertRaises(PeerError) as caught:
                    await manager.handle_call(call, wrap_validation_errors=False)

                self.assertIsInstance(caught.exception, ToolFailed)
                self.assertIsInstance(caught.exception.cause, TelegramForbiddenError)
                self.assertIs(caught.exception.cause, caught.exception.__cause__)
                failure = json.loads(caught.exception.message)
                self.assertEqual(failure['category'], 'rejected')
                self.assertNotIn('answer', failure)
                self.assertEqual(manager.failed_tools, set())
                self.assertEqual(manager.succeeded_tools, set())
                self.assertEqual(ctx.retries, {})
                self.assertEqual(http.calls, ['sendMessage'])
                self.assertEqual(hub.pending_count, 0)

    async def test_forbidden_is_a_failed_observation_not_a_retry_or_answer(self):
        peer, http, hub = self.peer_with_http(403, {
            'ok': False, 'error_code': 403, 'description': 'Forbidden: bot was blocked by the user'})
        failure = await self.recover(peer)
        self.assertEqual(failure['kind'], 'telegram_peer_failure')
        self.assertEqual(failure['category'], 'rejected')
        self.assertEqual(failure['delivery'], 'not_sent')
        self.assertFalse(failure['retry_allowed'])
        self.assertEqual(failure['error_type'], 'TelegramForbiddenError')
        self.assertIn('bot was blocked by the user', failure['error'])
        self.assertNotIn('answer', failure)
        self.assertEqual(http.calls, ['sendMessage'])
        self.assertEqual(hub.pending_count, 0)

    async def test_bad_request_during_resolution_preserves_original_exception(self):
        from aiogram.exceptions import TelegramBadRequest
        from pydantic_ai import ToolFailed
        from kibernikto.ai.agent.telegram.peer_agent import PeerError

        peer, http, hub = self.peer_with_http(400, {
            'ok': False, 'error_code': 400, 'description': 'Bad Request: chat not found'})
        peer.peer = '@missing_bot'
        with self.assertRaises(PeerError) as caught:
            await peer.run('question')
        self.assertIsInstance(caught.exception, ToolFailed)
        self.assertIs(caught.exception.cause, caught.exception.__cause__)
        self.assertIsInstance(caught.exception.cause, TelegramBadRequest)
        self.assertEqual(caught.exception.cause.method.chat_id, '@missing_bot')
        failure = await self.recover(peer, on_failure='MUST NOT REPLACE THE ORIGINAL ERROR')
        self.assertEqual(failure['category'], 'rejected')
        self.assertEqual(failure['delivery'], 'not_sent')
        self.assertEqual(failure['error_type'], 'TelegramBadRequest')
        self.assertIn('chat not found', failure['error'])
        self.assertEqual(http.calls, ['getChat', 'getChat'])
        self.assertEqual(hub.pending_count, 0)

    async def test_rate_limit_preserves_retry_after_without_resending(self):
        peer, http, hub = self.peer_with_http(429, {
            'ok': False, 'error_code': 429, 'description': 'Too Many Requests: retry after 17',
            'parameters': {'retry_after': 17}})
        failure = await self.recover(peer)
        self.assertEqual(failure['category'], 'rate_limited')
        self.assertEqual(failure['delivery'], 'not_sent')
        self.assertTrue(failure['retry_allowed'])
        self.assertEqual(failure['retry_after'], 17)
        self.assertEqual(failure['error_type'], 'TelegramRetryAfter')
        self.assertIn('17', failure['error'])
        self.assertEqual(http.calls, ['sendMessage'])
        self.assertEqual(hub.pending_count, 0)

    async def test_http_timeout_is_uncertain_not_a_safe_resend(self):
        from aiogram.exceptions import TelegramNetworkError
        from kibernikto.ai.agent.telegram.peer_agent import PeerError

        peer, http, hub = self.peer_with_http(200, {})
        original = TimeoutError('HTTP response was lost')

        async def lost_response():
            raise original

        http.response.text = lost_response
        failure = await self.recover(peer)
        self.assertEqual(failure['category'], 'network')
        self.assertEqual(failure['delivery'], 'unknown')
        self.assertFalse(failure['retry_allowed'])
        self.assertEqual(failure['error_type'], 'TelegramNetworkError')
        self.assertEqual(http.calls, ['sendMessage'])
        self.assertEqual(hub.pending_count, 0)
        with self.assertRaises(PeerError) as caught:
            await peer.run('question')
        self.assertIsInstance(caught.exception.cause, TelegramNetworkError)
        self.assertIs(caught.exception.cause.__cause__, original)

    async def test_peer_deadline_is_a_failure_not_a_nones_harness_timeout(self):
        from kibernikto.ai.agent.telegram.peer_agent import PeerError

        peer, http, hub = self.peer_with_http(200, {'ok': True, 'result': {
            'message_id': 10, 'date': 0, 'chat': {'id': 200, 'type': 'private'}, 'text': 'question'}},
            timeout=0.2)
        failure = await self.recover(peer)
        self.assertEqual(failure['category'], 'timeout')
        self.assertEqual(failure['delivery'], 'unknown')
        self.assertEqual(failure['timeout'], 0.2)
        self.assertFalse(failure['retry_allowed'])
        self.assertNotIn('Nones', json.dumps(failure))
        self.assertEqual(http.calls, ['sendMessage'])
        self.assertEqual(hub.pending_count, 0)
        with self.assertRaises(PeerError) as caught:
            await peer.run('question')
        self.assertIsInstance(caught.exception.cause, TimeoutError)
        self.assertIs(caught.exception.__cause__, caught.exception.cause)

    async def test_resolution_failure_cannot_have_sent_a_task(self):
        for failure_kind in ('network', 'timeout'):
            with self.subTest(failure_kind=failure_kind):
                peer, http, hub = self.peer_with_http(200, {}, timeout=0.02)
                peer.peer = '@remote_bot'

                async def interrupted_resolution():
                    if failure_kind == 'network':
                        raise TimeoutError('lost getChat response')
                    await asyncio.Event().wait()

                http.response.text = interrupted_resolution
                failure = await self.recover(peer)
                self.assertEqual(failure['category'], failure_kind)
                self.assertEqual(failure['delivery'], 'not_sent')
                self.assertEqual(http.calls, ['getChat'])
                self.assertEqual(hub.pending_count, 0)

    async def test_cancellation_propagates_through_parent_during_http_send(self):
        peer, http, hub = self.peer_with_http(200, {})
        entered = asyncio.Event()
        cleaned = asyncio.Event()

        async def blocked_response():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        http.response.text = blocked_response
        task = asyncio.create_task(self.recover(peer))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cleaned.is_set())
        self.assertEqual(http.calls, ['sendMessage'])
        self.assertEqual(hub.pending_count, 0)

    async def test_plain_subagent_without_containment_keeps_failed_outcome(self):
        peer, http, hub = self.peer_with_http(400, {
            'ok': False, 'error_code': 400, 'description': 'Bad Request: chat not found'})
        failure = await self.recover(peer, contain_errors=False)
        self.assertEqual(failure['category'], 'rejected')
        self.assertEqual(http.calls, ['sendMessage'])


if __name__ == '__main__':
    unittest.main()
