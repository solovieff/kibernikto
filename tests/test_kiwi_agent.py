"""Kiwi flight expert: search-only tools and per-conversation availability."""
import os
import unittest
from unittest.mock import patch

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import FunctionToolset, ModelResponse, RunContext, RunUsage, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.kiwi.config import KiwiSettings
from kibernikto.ai.agent.kiwi.expert import build_kiwi_expert, search_only_toolset
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.vkusvill.expert import CreditGatedSubAgents
from kibernikto.storage.models import ConversationInfo


class KiwiSettingsTests(unittest.TestCase):
    def test_defaults_and_env(self):
        settings = KiwiSettings(_env_file=None)
        self.assertEqual(settings.MCP_URL, 'https://mcp.kiwi.com')
        with patch.dict(os.environ, {'AGENT_KIWI_MAX_TOOL_CALLS': '30'}):
            self.assertEqual(KiwiSettings(_env_file=None).MAX_TOOL_CALLS, 30)


    def test_kiwi_output_limit_default_and_override(self):
        settings = KiwiSettings(_env_file=None)
        self.assertEqual(settings.MODEL_MAX_TOKENS, 8192)
        expert = build_kiwi_expert(settings=settings, model=TestModel(), toolset=FunctionToolset())
        self.assertEqual(expert.agent.model_settings['max_tokens'], 8192)
        with patch.dict(os.environ, {'AGENT_KIWI_MODEL_MAX_TOKENS': '12000'}):
            configured = KiwiSettings(_env_file=None)
            self.assertEqual(build_kiwi_expert(settings=configured, model=TestModel(),
                                               toolset=FunctionToolset()).agent.model_settings['max_tokens'], 12000)


class KiwiMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_search_is_available(self):
        server = FunctionToolset()

        @server.tool_plain(name='search-flight')
        def search_flight(query: str) -> str:
            return f'flight {query}'

        @server.tool_plain(name='feedback-to-devs')
        def feedback(text: str) -> str:
            raise AssertionError('feedback must not be callable')

        toolset = search_only_toolset(server)
        ctx = RunContext(deps=TelegramDeps(), model=TestModel(), usage=RunUsage())
        async with toolset:
            tools = await toolset.get_tools(ctx)
            self.assertEqual(set(tools), {'search-flight'})
            self.assertEqual(await toolset.call_tool('search-flight', {'query': 'Paris'}, ctx, tools['search-flight']),
                             'flight Paris')

        # A model cannot call feedback: the tool manager sees only the filtered definitions.
        def force_feedback(messages, info):
            if any(part.part_kind == 'retry-prompt' for m in messages for part in m.parts):
                return ModelResponse(parts=[TextPart('not allowed')])
            return ModelResponse(parts=[ToolCallPart('feedback-to-devs', {'text': 'x'})])

        agent = build_kiwi_expert(model=FunctionModel(force_feedback), toolset=server).agent
        result = await agent.run('send feedback', deps=TelegramDeps())
        self.assertEqual(result.output, 'not allowed')

    async def test_expert_can_execute_search_offline(self):
        server = FunctionToolset()

        @server.tool_plain(name='search-flight')
        def search_flight(query: str) -> str:
            return f'flight {query}'

        expert = build_kiwi_expert(model=TestModel(), toolset=server)
        result = await expert.agent.run('find flight', deps=TelegramDeps())
        calls = [p.tool_name for m in result.all_messages() for p in m.parts if p.part_kind == 'tool-call']
        self.assertIn('search-flight', calls)


class KiwiGatingTests(unittest.IsolatedAsyncioTestCase):
    def context(self, credits, personal):
        return RunContext(deps=TelegramDeps(is_personal=personal, chat_info=ConversationInfo(credits=credits)),
                          model=TestModel(), usage=RunUsage(), conversation_id='42')

    async def test_two_experts_have_independent_thresholds(self):
        kiwi = build_kiwi_expert(model=TestModel(), toolset=FunctionToolset())
        other = SubAgent(kiwi.agent, name='vkusvill')
        roster = CreditGatedSubAgents(agents=[kiwi, other], min_credits=2000,
                                      gated_thresholds={'kiwi': 3000, 'vkusvill': 2000})
        for credits, personal, expected in [(2000, True, set()), (2001, True, {'vkusvill'}),
                                            (3001, True, {'kiwi', 'vkusvill'}), (5000, False, set())]:
            with self.subTest(credits=credits, personal=personal):
                run = await roster.for_run(self.context(credits, personal))
                self.assertEqual({a.name for a in run.agents}, expected)
