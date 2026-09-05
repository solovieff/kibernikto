"""Offline integration tests: real aiogram dispatch and PydanticAI delegation."""
import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

# Import-time singletons must never pick up production credentials in tests.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update, User


def message(message_id: int, sender: int = 200, chat_id: int = 200,
            reply_id: int | None = None, text: str = 'answer') -> Message:
    reply = None
    if reply_id is not None:
        reply = Message(message_id=reply_id, date=datetime.now(timezone.utc),
                        chat=Chat(id=chat_id, type='private'),
                        from_user=User(id=100, is_bot=True, first_name='caller'), text='question')
    return Message(message_id=message_id, date=datetime.now(timezone.utc),
                   chat=Chat(id=chat_id, type='private'),
                   from_user=User(id=sender, is_bot=True, first_name='peer'),
                   text=text, reply_to_message=reply)


class PeerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Cold PydanticAI imports are CPU-bound, not an event-loop regression.
        asyncio.get_running_loop().slow_callback_duration = 10

    async def test_reply_arrives_through_existing_dispatcher(self):
        from kibernikto.telegram.peer_hub import PeerHub
        from kibernikto.telegram.middleware.middleware_peer import PeerMiddleware

        bot = Bot('100:offline-test-token')
        hub = PeerHub()
        dispatcher = Dispatcher()
        dispatcher.message.outer_middleware(PeerMiddleware(hub))
        ordinary = AsyncMock()
        async def ordinary_handler(event):
            await ordinary(event)

        dispatcher.message.register(ordinary_handler)
        sent = asyncio.Event()

        async def send(**kwargs):
            self.assertEqual(kwargs['chat_id'], 200)
            self.assertIsNone(kwargs['parse_mode'])
            sent.set()
            return message(10, sender=100)

        bot.send_message = AsyncMock(side_effect=send)
        task = asyncio.create_task(hub.request(bot, 200, 'question', timeout=1))
        await sent.wait()
        await dispatcher.feed_update(bot, Update(update_id=1, message=message(11, reply_id=10)))
        self.assertEqual(await task, 'answer')
        ordinary.assert_not_awaited()
        self.assertEqual(hub.pending_count, 0)
        await bot.session.close()

    async def test_peer_is_a_real_subagent_and_returns_real_history(self):
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai_harness.subagents import SubAgent, SubAgents
        from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
        from kibernikto.telegram.peer_hub import PeerHub
        from kibernikto.telegram.middleware.middleware_peer import PeerMiddleware

        bot = Bot('100:offline-test-token')
        hub = PeerHub()
        dispatcher = Dispatcher()
        dispatcher.message.outer_middleware(PeerMiddleware(hub))
        sent = asyncio.Event()

        async def send(**kwargs):
            self.assertEqual(kwargs['text'], 'question')
            sent.set()
            return message(10, sender=100)

        bot.send_message = AsyncMock(side_effect=send)
        peer = TelegramPeerAgent(peer=200, name='remote', description='Remote expert', bot=bot, hub=hub)
        self.assertIsInstance(peer, KiberniktoAgent)

        def parent_model(messages, info):
            if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
                return ModelResponse(parts=[TextPart('delegation completed')])
            return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'remote', 'task': 'question'})])

        parent = Agent(FunctionModel(parent_model), capabilities=[SubAgents(agents=[SubAgent(peer)])])
        task = asyncio.create_task(parent.run('delegate'))
        await asyncio.wait_for(sent.wait(), 3)
        await dispatcher.feed_update(bot, Update(update_id=1, message=message(11, reply_id=10)))
        result = await task
        self.assertEqual(result.output, 'delegation completed')
        returns = [p.content for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
        self.assertIn('answer', returns)
        self.assertEqual(hub.pending_count, 0)
        await bot.session.close()

    async def test_app_installs_peer_middleware_before_access_checks(self):
        from kibernikto.telegram.agent.telegram_app import TelegramApp
        from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
        from kibernikto.telegram.middleware.middleware_peer import PeerMiddleware
        from pydantic_ai.models.test import TestModel
        from kibernikto.telegram.config import TELEGRAM_SETTINGS
        from unittest.mock import patch

        with patch.object(TELEGRAM_SETTINGS, 'BOT_KEY', '100:offline-test-token'):
            app = TelegramApp.from_agent(TelegramAgent(model=TestModel()))
        self.assertIsInstance(app.dispatcher.message.outer_middleware[0], PeerMiddleware)
        self.assertIs(app.peer_hub, app.dispatcher.message.outer_middleware[0].hub)
        await app.bot.session.close()

    async def test_app_shutdown_closes_peer_hub(self):
        from kibernikto.telegram.agent.telegram_app import TelegramApp
        bot = Bot('100:offline-test-token')
        app = TelegramApp(bot, Dispatcher())
        bot.send_message = AsyncMock(return_value=message(10, sender=100))
        await app.dispatcher.emit_shutdown(bot=bot)
        with self.assertRaises(RuntimeError):
            await app.peer_hub.request(bot, 200, 'question', timeout=1)
        await bot.session.close()

    async def test_route_is_inherited_from_dispatcher_and_deps(self):
        from kibernikto.telegram.agent.telegram_app import TelegramApp
        from kibernikto.ai.agent.telegram.deps import TelegramDeps
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
        from pydantic_ai.messages import ModelResponse
        from aiogram import F

        bot = Bot('100:offline-test-token')
        app = TelegramApp(bot, Dispatcher())
        peer = TelegramPeerAgent(peer=200, name='remote', description='Remote expert')
        ready = asyncio.Event()
        outputs = []

        async def send(**kwargs):
            ready.set()
            return message(10, sender=100)

        bot.send_message = AsyncMock(side_effect=send)

        async def handle(event):
            result = await peer.run(event.text, deps=TelegramDeps(message=event))
            self.assertIsInstance(result.response, ModelResponse)
            self.assertEqual(result.response.parts[0].content, 'answer')
            self.assertEqual(len(result.new_messages()), 2)
            outputs.append(result.output)

        app.dispatcher.message.register(handle, F.from_user.id == 300)
        task = asyncio.create_task(app.dispatcher.feed_update(bot, Update(update_id=1,
                                  message=message(1, sender=300, chat_id=300, text='question'))))
        await asyncio.wait_for(ready.wait(), 3)
        await app.dispatcher.feed_update(bot, Update(update_id=2, message=message(11, reply_id=10)))
        await task
        self.assertEqual(outputs, ['answer'])
        await bot.session.close()

    async def test_edited_human_message_inherits_peer_route(self):
        from aiogram import F
        from kibernikto.ai.agent.telegram.deps import TelegramDeps
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
        from kibernikto.telegram.agent.telegram_app import TelegramApp
        from kibernikto.telegram.peer_hub import current_peer_hub

        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        peer = TelegramPeerAgent(peer=200, name='remote', description='expert')
        replies = []
        outputs = []

        async def send(**kwargs):
            replies.append(asyncio.create_task(app.dispatcher.feed_update(
                bot, Update(update_id=2, message=message(11, reply_id=10)))))
            return message(10, sender=100)

        bot.send_message = AsyncMock(side_effect=send)

        async def handle(event):
            self.assertIs(current_peer_hub.get(None), app.peer_hub)
            result = await peer.run(event.text, deps=TelegramDeps(message=event))
            outputs.append(result.output)

        app.dispatcher.edited_message.register(handle, ~F.from_user.is_bot)
        human = message(1, sender=300, chat_id=300, text='edited question').model_copy(
            update={'from_user': User(id=300, is_bot=False, first_name='human')})
        previous_hub = current_peer_hub.get(None)
        await asyncio.wait_for(app.dispatcher.feed_update(
            bot, Update(update_id=1, edited_message=human)), 3)
        await asyncio.gather(*replies)
        self.assertEqual(outputs, ['answer'])
        self.assertIs(current_peer_hub.get(None), previous_hub)
        self.assertEqual(app.peer_hub.pending_count, 0)

    async def test_edited_peer_reply_does_not_complete_pending_request(self):
        from kibernikto.telegram.agent.telegram_app import TelegramApp

        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        sent = asyncio.Event()

        async def send(**kwargs):
            sent.set()
            return message(10, sender=100)

        bot.send_message = AsyncMock(side_effect=send)
        task = asyncio.create_task(app.peer_hub.request(bot, 200, 'question', timeout=3))
        await asyncio.wait_for(sent.wait(), 1)
        await app.dispatcher.feed_update(bot, Update(
            update_id=1, edited_message=message(11, reply_id=10, text='edited answer')))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        await app.dispatcher.feed_update(bot, Update(
            update_id=2, message=message(12, reply_id=10, text='new answer')))
        self.assertEqual(await task, 'new answer')

    async def test_shutdown_cancels_and_awaits_username_resolution(self):
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
        from kibernikto.telegram.agent.telegram_app import TelegramApp

        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        entered = asyncio.Event()
        cleaned_up = asyncio.Event()

        async def resolve(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned_up.set()

        bot.get_chat = AsyncMock(side_effect=resolve)
        bot.send_message = AsyncMock()
        peer = TelegramPeerAgent(peer='@remote_bot', name='remote', description='expert',
                                 bot=bot, hub=app.peer_hub)
        task = asyncio.create_task(peer.run('question'))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertEqual(app.peer_hub.pending_count, 0)
            await app.dispatcher.emit_shutdown(bot=bot)
            self.assertTrue(task.cancelled())
            self.assertTrue(cleaned_up.is_set())
            bot.send_message.assert_not_awaited()
            await app.peer_hub.close()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_closed_hub_rejects_run_before_username_resolution(self):
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
        from kibernikto.telegram.peer_hub import PeerHub

        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        hub = PeerHub()
        bot.get_chat = AsyncMock(return_value=Chat(id=200, type='private'))
        bot.send_message = AsyncMock()
        peer = TelegramPeerAgent(peer='@remote_bot', name='remote', description='expert',
                                 bot=bot, hub=hub)
        await hub.close()
        with self.assertRaisesRegex(RuntimeError, 'Peer hub is closed'):
            await peer.run('question')
        bot.get_chat.assert_not_awaited()
        bot.send_message.assert_not_awaited()
        self.assertEqual(hub.pending_count, 0)

    async def test_unsupported_options_fail_before_sending(self):
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
        from kibernikto.telegram.peer_hub import PeerHub
        bot = Bot('100:offline-test-token')
        bot.send_message = AsyncMock()
        peer = TelegramPeerAgent(peer=200, name='remote', description='expert', bot=bot, hub=PeerHub())
        for options in ({'output_type': int}, {'message_history': [object()]}, {'deferred_tool_results': object()}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                await peer.run('question', **options)
        bot.send_message.assert_not_awaited()
        await bot.session.close()

    async def test_peer_validates_before_network_and_bounds_resolution(self):
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
        from kibernikto.telegram.peer_hub import PeerHub

        bot = Bot('100:offline-test-token')
        hub = PeerHub()
        for peer in (0, -1, True, 'username-without-at', '@bad space'):
            with self.subTest(peer=peer), self.assertRaises(ValueError):
                TelegramPeerAgent(peer=peer, name='remote', description='expert', bot=bot, hub=hub)
        for timeout in (0, -1, float('nan'), float('inf')):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                TelegramPeerAgent(peer=200, name='remote', description='expert', timeout=timeout)
        bot.get_chat = AsyncMock(side_effect=lambda *args: None)
        peer = TelegramPeerAgent(peer='@remote_bot', name='remote', description='expert', bot=bot, hub=hub)
        with self.assertRaises(ValueError):
            await peer.run('x' * 4097)
        bot.get_chat.assert_not_awaited()

        async def stuck(*args):
            await asyncio.Event().wait()
        bot.get_chat = AsyncMock(side_effect=stuck)
        peer = TelegramPeerAgent(peer='@remote_bot', name='remote', description='expert', bot=bot, hub=hub, timeout=0.02)
        from kibernikto.ai.agent.telegram.peer_agent import PeerError
        with self.assertRaises(PeerError) as caught:
            await asyncio.wait_for(peer.run('question'), 1)
        self.assertEqual(caught.exception.category, 'timeout')
        self.assertIsInstance(caught.exception.__cause__, TimeoutError)
        self.assertEqual(hub.pending_count, 0)
        await bot.session.close()


if __name__ == '__main__':
    unittest.main()
