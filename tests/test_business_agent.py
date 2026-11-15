"""Business expert: optional DaData auth, tool safety and per-chat gating."""
import importlib
import importlib.util
import os
import unittest
from unittest.mock import patch

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import FunctionToolset, ModelResponse, RunContext, RunUsage, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.harness.delegation import CreditGatedSubAgents
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent
from kibernikto.ai.agent.addons.travel.config import TRAVEL_SETTINGS
from kibernikto.ai.agent.addons.vkusvill.config import VKUSVILL_SETTINGS
from kibernikto.storage.base import MemoryHistoryStorage
from kibernikto.storage.models import ConversationInfo


def business_module():
    if importlib.util.find_spec('kibernikto.ai.agent.addons.business') is None:
        raise AssertionError('business expert package is missing')
    return importlib.import_module('kibernikto.ai.agent.addons.business.agent')


class BusinessTests(unittest.IsolatedAsyncioTestCase):
    def context(self, credits, personal):
        return RunContext(deps=TelegramDeps(is_personal=personal, chat_info=ConversationInfo(credits=credits)),
                          model=TestModel(), usage=RunUsage(), conversation_id='42')

    async def test_settings_are_optional_and_secret_redacted(self):
        business_module()
        config = importlib.import_module('kibernikto.ai.agent.addons.business.config')
        with patch.dict(os.environ, {}, clear=True):
            missing = config.BusinessSettings(_env_file=None)
            self.assertFalse(missing.configured)
            with patch.dict(os.environ, {'AGENT_BUSINESS_DADATA_TOKEN': 'demo-api:demo-secret'}):
                configured = config.BusinessSettings(_env_file=None)
                self.assertTrue(configured.configured)
                self.assertNotIn('demo-secret', repr(configured))
            for bad in ('', 'only-one-key', ':secret', 'api:', 'api:secret:unexpected'):
                with self.subTest(token=bad):
                    self.assertFalse(config.BusinessSettings(_env_file=None, DADATA_TOKEN=bad).configured)

    async def test_expert_is_opt_in_and_needs_a_token(self):
        business_module()
        config = importlib.import_module('kibernikto.ai.agent.addons.business.config')
        token = 'demo-api:demo-secret'
        self.assertFalse(config.BusinessSettings(_env_file=None).ENABLED)
        off = config.BusinessSettings(_env_file=None, DADATA_TOKEN=token)
        self.assertTrue(off.configured)
        self.assertFalse(off.active)
        self.assertTrue(config.BusinessSettings(_env_file=None, DADATA_TOKEN=token, ENABLED=True).active)
        self.assertFalse(config.BusinessSettings(_env_file=None, ENABLED=True).active)

    async def test_authorization_uses_bearer_auth_not_url(self):
        business = business_module()
        config = importlib.import_module('kibernikto.ai.agent.addons.business.config')
        settings = config.BusinessSettings(_env_file=None, DADATA_TOKEN='demo-api:demo-secret')
        toolset = business.build_dadata_toolset(settings)
        transport = toolset.client.transport
        self.assertEqual(transport.url, 'https://mcp.dadata.ru/mcp')
        self.assertEqual(type(transport.auth).__name__, 'BearerAuth')
        import httpx2
        request = httpx2.Request('POST', transport.url)
        signed = next(transport.auth.auth_flow(request))
        self.assertEqual(signed.headers['Authorization'], 'Bearer demo-api:demo-secret')
        self.assertNotIn('demo-secret', repr(toolset))
        self.assertNotIn('demo-secret', transport.url)

    async def test_only_reviewed_tools_are_visible_and_unknown_call_fails(self):
        business = business_module()
        server = FunctionToolset()
        for name in ('find_party', 'clean_address', 'find_company_by_email', 'find_company_by_domain', 'future_write'):
            def tool():
                return 'ok'
            server.add_function(tool, name=name)
        toolset = business.dadata_toolset(server)
        async with toolset:
            tools = await toolset.get_tools(self.context(3000, True))
        self.assertEqual(set(tools), {'find_party', 'clean_address', 'find_company_by_email', 'find_company_by_domain'})
        def model(messages, info):
            if any((p.part_kind == 'retry-prompt' or getattr(p, 'outcome', None) == 'retried') for m in messages for p in m.parts):
                return ModelResponse(parts=[TextPart('not allowed')])
            return ModelResponse(parts=[ToolCallPart('future_write', {})])
        agent = business.build_business_expert(model=FunctionModel(model), toolset=server).agent
        result = await agent.run('call forbidden tool', deps=TelegramDeps())
        self.assertEqual(result.output, 'not allowed')

    async def test_real_mcp_protocol_with_in_process_server(self):
        business = business_module()
        from fastmcp import Client
        from mcp.server.mcpserver import MCPServer
        from pydantic_ai.mcp import MCPToolset
        server = MCPServer('fake-dadata')
        @server.tool()
        def find_party(query: str) -> dict:
            return {'inn': query, 'name': 'Test company'}
        def model(messages, info):
            for m in messages:
                for p in m.parts:
                    if isinstance(p, ToolReturnPart) and p.tool_name == 'find_party':
                        return ModelResponse(parts=[TextPart(str(p.content))])
            return ModelResponse(parts=[ToolCallPart('find_party', {'query': '7707083893'})])
        agent = business.build_business_expert(model=FunctionModel(model),
                                               toolset=MCPToolset(Client(server))).agent
        result = await agent.run('find company', deps=TelegramDeps())
        self.assertIn('7707083893', result.output)
        self.assertIn('Test company', result.output)

    async def test_no_key_means_no_business_agent(self):
        business_module()
        config = importlib.import_module('kibernikto.ai.agent.addons.business.config')
        with patch.object(config.BUSINESS_SETTINGS, 'DADATA_TOKEN', None), \
             patch.object(TRAVEL_SETTINGS, 'ENABLED', False), \
             patch.object(VKUSVILL_SETTINGS, 'ENABLED', False):
            parent = build_multi_agent()
            from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents
            found = []
            parent.root_capability.apply(lambda c: found.append(c) if isinstance(c, KiberniktoSubAgents) else None)
            self.assertNotIn('business', {a.name for cap in found for a in cap.agents})

    async def test_invalid_token_warns_without_disclosing_it(self):
        business_module()
        config = importlib.import_module('kibernikto.ai.agent.addons.business.config')
        from pydantic import SecretStr
        with patch.object(config.BUSINESS_SETTINGS, 'ENABLED', True), \
             patch.object(config.BUSINESS_SETTINGS, 'DADATA_TOKEN', SecretStr('bad-secret-token')), \
             patch.object(TRAVEL_SETTINGS, 'ENABLED', False), \
             patch.object(VKUSVILL_SETTINGS, 'ENABLED', False), \
             self.assertLogs('kibernikto.ai.agent.telegram.multi_agent', level='WARNING') as logs:
            build_multi_agent()
        self.assertIn('AGENT_BUSINESS_DADATA_TOKEN', str(logs.output))
        self.assertNotIn('bad-secret-token', str(logs.output))

    async def test_parent_delegates_only_private_and_rich(self):
        business = business_module()
        config = importlib.import_module('kibernikto.ai.agent.addons.business.config')
        from pydantic import SecretStr
        seen = []
        server = FunctionToolset()
        @server.tool_plain(name='find_party')
        def find_party() -> str:
            seen.append('called')
            return 'company-verified-from-dadata'
        def child(messages, info):
            if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
                return ModelResponse(parts=[TextPart('company-verified-from-dadata')])
            return ModelResponse(parts=[ToolCallPart('find_party', {})])
        expert = business.build_business_expert(model=FunctionModel(child), toolset=server)
        def parent_model(messages, info):
            returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
            if returns:
                return ModelResponse(parts=[TextPart(str(returns[-1].content))])
            if any((p.part_kind == 'retry-prompt' or getattr(p, 'outcome', None) == 'retried') for m in messages for p in m.parts):
                return ModelResponse(parts=[TextPart('expert unavailable')])
            return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'business', 'task': 'find company'})])
        with patch.object(config.BUSINESS_SETTINGS, 'ENABLED', True), \
             patch.object(config.BUSINESS_SETTINGS, 'DADATA_TOKEN', SecretStr('demo-api:demo-secret')), \
             patch.object(TRAVEL_SETTINGS, 'ENABLED', False), \
             patch.object(VKUSVILL_SETTINGS, 'ENABLED', False), \
             patch('kibernikto.ai.agent.addons.business.agent.build_business_expert', return_value=expert), \
             patch('kibernikto.ai.agent.telegram.multi_agent.get_history_storage', return_value=MemoryHistoryStorage()), \
             patch('kibernikto.ai.agent.telegram.multi_agent.ConversationMemory', return_value=AbstractCapability()), \
             patch.object(AGENT_KIBERNIKTO_SETTINGS, 'RICH_CREDITS', 500):
            parent = build_multi_agent()
            for credits, personal, expected in [(499, True, 0), (500, True, 1), (9000, False, 0)]:
                with self.subTest(credits=credits, personal=personal):
                    seen.clear()
                    deps = TelegramDeps(is_personal=personal, chat_info=ConversationInfo(credits=credits), billable=False)
                    with parent.override(model=FunctionModel(parent_model)):
                        result = await parent.run('find company', deps=deps,
                                                  conversation_id=f'business-{credits}-{personal}')
                    self.assertEqual(len(seen), expected, result.output)
                    if expected:
                        self.assertIn('company-verified-from-dadata', result.output)

    async def test_business_roster_is_gated_with_travel(self):
        business_module()
        config = importlib.import_module('kibernikto.ai.agent.addons.business.config')
        from pydantic import SecretStr
        with patch.object(config.BUSINESS_SETTINGS, 'ENABLED', True), \
             patch.object(config.BUSINESS_SETTINGS, 'DADATA_TOKEN', SecretStr('demo-api:demo-secret')), \
             patch.object(TRAVEL_SETTINGS, 'ENABLED', True), \
             patch('kibernikto.ai.agent.addons.travel.tutu.config.TUTU_SETTINGS.ENABLED', True), \
             patch.object(VKUSVILL_SETTINGS, 'ENABLED', False), \
             patch.object(AGENT_KIBERNIKTO_SETTINGS, 'RICH_CREDITS', 500):
            parent = build_multi_agent()
            rosters = []
            parent.root_capability.apply(lambda c: rosters.append(c) if isinstance(c, CreditGatedSubAgents) else None)
            for credits, personal, expected in [(499, True, set()), (500, True, {'business', 'travel'}),
                                                (9000, False, set())]:
                run = await rosters[0].for_run(self.context(credits, personal))
                self.assertEqual({a.name for a in run.agents} & {'business', 'travel'}, expected)
