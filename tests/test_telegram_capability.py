"""build_telegram_agent: plain Agent with Telegram capability, bot-named persona and reaction metadata."""

import os
import unittest

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.identity import BotIdentity, set_bot_identity
from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent


class BuildTelegramAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        set_bot_identity(BotIdentity(username='cyber_bot', full_name='Кибер Никто'))
        self.addCleanup(set_bot_identity, None)

    async def test_is_a_plain_agent_with_telegram_context_and_reaction(self) -> None:
        agent = build_telegram_agent(model=TestModel(call_tools=[]), name='tg-cap', history_storage=None,
                                     reaction='👀')
        self.assertIs(type(agent), Agent)
        deps = TelegramDeps(conversation_context='[Current conversation context] chat_type: private')
        with capture_run_messages() as messages:
            result = await agent.run('hi', deps=deps)
        instructions = messages[0].instructions or ''
        self.assertIn('@cyber_bot', instructions)
        self.assertIn('chat_type: private', instructions)
        self.assertIn('Current date:', instructions)
        self.assertEqual(result.metadata['reaction'], '👀')
