"""Exercise the public mixed local/remote builder with actual harness delegation."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from tests.test_telegram_peer import message
from tests.test_peer_builder import orchestrators
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
from kibernikto.telegram.agent.telegram_app import TelegramApp


class PublicBuilderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_builder_delegates_to_poet_and_returns_its_answer(self):
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        sent = asyncio.Event()

        async def send(**kwargs):
            self.assertEqual(kwargs['text'], 'Write a poem')
            sent.set()
            return message(10, sender=100)

        bot.send_message = AsyncMock(side_effect=send)
        poet = TelegramPeerAgent(peer=200, name='poet', description='Writes poems', bot=bot, hub=app.peer_hub)
        with patch.object(orchestrators, 'infer_kibernikto_model', return_value=TestModel()):
            agent = orchestrators.build_subagents_agent_with_tg_peers([poet])

        def model(messages, info):
            returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
            if returns:
                return ModelResponse(parts=[TextPart(str(returns[-1].content))])
            return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'poet', 'task': 'Write a poem'})])

        with agent.override(model=FunctionModel(model)):
            task = asyncio.create_task(agent.run('Ask the poet'))
            await asyncio.wait_for(sent.wait(), 3)
            await app.dispatcher.feed_update(bot, Update(update_id=1, message=message(11, reply_id=10, text='A small poem.')))
            result = await asyncio.wait_for(task, 3)
        self.assertEqual(result.output, 'A small poem.')
        self.assertEqual(app.peer_hub.pending_count, 0)
        bot.send_message.assert_awaited_once()

    async def test_public_builder_timeout_is_a_failed_tool_result(self):
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        app = TelegramApp(bot, Dispatcher())
        self.addAsyncCleanup(app.peer_hub.close)
        bot.send_message = AsyncMock(return_value=message(10, sender=100))
        peer = TelegramPeerAgent(peer=200, name='poet', description='Writes poems',
                                 bot=bot, hub=app.peer_hub, timeout=0.2)
        with patch.object(orchestrators, 'infer_kibernikto_model', return_value=TestModel()):
            agent = orchestrators.build_subagents_agent_with_tg_peers([peer])

        def model(messages, info):
            returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
            if returns:
                self.assertEqual(returns[-1].outcome, 'failed')
                self.assertIn('timeout', str(returns[-1].content))
                self.assertNotIn('Nones', str(returns[-1].content))
                return ModelResponse(parts=[TextPart('The poet did not answer.')])
            return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'poet', 'task': 'Write a poem'})])

        with agent.override(model=FunctionModel(model)):
            result = await agent.run('Ask the poet')
        self.assertEqual(result.output, 'The poet did not answer.')
        self.assertEqual(app.peer_hub.pending_count, 0)
        bot.send_message.assert_awaited_once()
