"""Offline coverage for the VkusVill MCP agent: settings, toolset wiring, behaviour prompt."""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from fastmcp.client.auth import OAuth
from pydantic import ValidationError
from pydantic_ai import FunctionToolset, ModelMessage, ModelRequest, ModelResponse, RunContext, RunUsage, TextPart
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent
from kibernikto.ai.agent.vkusvill.agent import build_vkusvill_agent
from kibernikto.ai.agent.vkusvill.config import (
    DEFAULT_MCP_URL,
    DEFAULT_SCOPES,
    VKUSVILL_SETTINGS,
    VkusvillSettings,
    resolve_token_dir,
)
from kibernikto.ai.agent.vkusvill.expert import (
    VKUSVILL_EXPERT_NAME,
    CreditGatedSubAgents,
    build_vkusvill_expert,
    expert_allowed,
)
from kibernikto.ai.agent.vkusvill.mcp import build_vkusvill_toolset
from kibernikto.storage.models import ConversationInfo


class VkusvillSettingsTests(unittest.TestCase):
    def test_defaults_are_anonymous(self) -> None:
        settings = VkusvillSettings()
        self.assertEqual(settings.AUTH_MODE, 'anonymous')
        self.assertEqual(settings.MCP_URL, DEFAULT_MCP_URL)
        self.assertEqual(settings.NAME, 'vkusvill')
        self.assertEqual(settings.OAUTH_SCOPES, DEFAULT_SCOPES)
        self.assertIsNone(settings.MODEL_NAME)

    def test_oauth_requires_credentials(self) -> None:
        with self.assertRaises(ValidationError):
            VkusvillSettings(AUTH_MODE='oauth')

    def test_oauth_accepts_full_credentials(self) -> None:
        settings = VkusvillSettings(AUTH_MODE='oauth', OAUTH_CLIENT_ID='cid', OAUTH_CLIENT_SECRET='secret')
        self.assertEqual(settings.OAUTH_CLIENT_ID, 'cid')

    def test_token_dir_defaults_under_filestore(self) -> None:
        settings = VkusvillSettings()
        with patch('kibernikto.ai.agent.vkusvill.config.STORAGE_SETTINGS') as storage:
            storage.FILESTORE_LOCATION = '/tmp/kibernikto-store'
            self.assertEqual(resolve_token_dir(settings), Path('/tmp/kibernikto-store/vkusvill-oauth'))

    def test_token_dir_honours_explicit_override(self) -> None:
        with TemporaryDirectory() as tmp:
            settings = VkusvillSettings(OAUTH_TOKEN_DIR=tmp)
            self.assertEqual(resolve_token_dir(settings), Path(tmp))


class VkusvillToolsetTests(unittest.TestCase):
    def test_anonymous_toolset_points_at_the_public_endpoint(self) -> None:
        toolset = build_vkusvill_toolset()
        self.assertIsInstance(toolset, MCPToolset)
        self.assertEqual(str(toolset.client.transport.url), DEFAULT_MCP_URL)

    def test_oauth_toolset_carries_credentials_and_creates_the_token_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            token_dir = Path(tmp) / 'tokens'
            settings = VkusvillSettings(
                AUTH_MODE='oauth',
                OAUTH_CLIENT_ID='cid',
                OAUTH_CLIENT_SECRET='secret',
                OAUTH_TOKEN_DIR=str(token_dir),
            )
            toolset = build_vkusvill_toolset(settings)
            auth = toolset.client.transport.auth
            self.assertIsInstance(auth, OAuth)
            self.assertEqual(auth._static_client_info.client_id, 'cid')
            self.assertTrue(token_dir.is_dir())


class ScriptedModel:
    """Answers `ok` and records every request so instructions can be inspected."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(messages[-1])
        return ModelResponse(parts=[TextPart('ok')])


class VkusvillAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.model = ScriptedModel()
        self.agent = build_vkusvill_agent(
            model=FunctionModel(self.model),
            toolset=FunctionToolset(),
            history_storage=None,
        )

    def test_agent_is_named_and_owns_the_default_mcp_toolset(self) -> None:
        agent = build_vkusvill_agent(model=FunctionModel(self.model), history_storage=None)
        self.assertEqual(agent.name, 'vkusvill')
        self.assertIsInstance(agent.toolsets[-1], MCPToolset)

    def test_agent_accepts_an_injected_toolset(self) -> None:
        self.assertEqual(self.agent.name, 'vkusvill')
        self.assertIsInstance(self.agent.toolsets[-1], FunctionToolset)

    def test_tool_calls_are_serial(self) -> None:
        self.assertFalse(self.agent.model_settings['parallel_tool_calls'])

    async def test_instructions_carry_the_shopping_contract(self) -> None:
        await self.agent.run('привет', deps=TelegramDeps())
        instructions = self.model.requests[-1].instructions or ''
        self.assertIn('ВкусВилл', instructions)
        self.assertIn('Не занимайся исследованиями', instructions)
        self.assertIn('Не переспрашивай по понятному списку', instructions)
        self.assertIn('не понимает «сок в маленькой таре»', instructions)
        self.assertIn('sort="price_asc"', instructions)
        self.assertIn('category_id', instructions)
        self.assertIn('Больше 10 вызовов инструментов', instructions)
        self.assertIn('mode="custom"', instructions)
        self.assertIn('vkusvill_product_details', instructions)
        self.assertIn('vkusvill_cart_link_create', instructions)
        self.assertIn('vkusvill.ru/mobile?basket&share=', instructions)
        self.assertIn('не оформляешь заказ', instructions)

    async def test_generic_persona_is_not_injected(self) -> None:
        await self.agent.run('привет', deps=TelegramDeps())
        instructions = self.model.requests[-1].instructions or ''
        self.assertNotIn('Kibernikto', instructions)


class VkusvillExpertGateTests(unittest.TestCase):
    def test_personal_chat_needs_more_than_the_floor(self) -> None:
        self.assertTrue(expert_allowed(credits=2500, is_personal=True, min_credits=2000))
        self.assertFalse(expert_allowed(credits=2000, is_personal=True, min_credits=2000))
        self.assertFalse(expert_allowed(credits=500, is_personal=True, min_credits=2000))

    def test_group_chat_never_gets_the_shop(self) -> None:
        self.assertFalse(expert_allowed(credits=999_999, is_personal=False, min_credits=0))
        self.assertFalse(expert_allowed(credits=999_999, is_personal=False, min_credits=2000))

    def test_no_floor_allows_any_personal_chat(self) -> None:
        self.assertTrue(expert_allowed(credits=0, is_personal=True, min_credits=0))

    def test_expert_is_a_named_subagent_with_routing_description(self) -> None:
        expert = build_vkusvill_expert()
        self.assertEqual(expert.name, VKUSVILL_EXPERT_NAME)
        self.assertIn('ВкусВилл', expert.description)

    def test_default_settings_keep_the_expert_off(self) -> None:
        self.assertFalse(VkusvillSettings().ENABLED)
        self.assertEqual(VkusvillSettings().MIN_CREDITS, 2000)

    def test_default_multi_agent_roster_has_no_shop(self) -> None:
        with patch.object(VKUSVILL_SETTINGS, 'ENABLED', False), \
                patch('kibernikto.ai.agent.telegram.multi_agent.KiberniktoSubAgents') as roster:
            build_multi_agent()
        names = [sub.name or sub.agent.name for sub in roster.call_args.kwargs['agents']]
        self.assertNotIn(VKUSVILL_EXPERT_NAME, names)

    def test_enabled_multi_agent_registers_the_gated_roster(self) -> None:
        with patch.object(VKUSVILL_SETTINGS, 'ENABLED', True), \
                patch('kibernikto.ai.agent.vkusvill.expert.CreditGatedSubAgents') as gated, \
                patch('kibernikto.ai.agent.vkusvill.expert.build_vkusvill_expert') as expert:
            build_multi_agent()
        expert.assert_called_once_with()
        self.assertEqual(gated.call_args.kwargs['min_credits'], VKUSVILL_SETTINGS.MIN_CREDITS)
        self.assertIn(expert.return_value, gated.call_args.kwargs['agents'])


class CreditGatedRosterTests(unittest.IsolatedAsyncioTestCase):
    def make_ctx(self, *, credits: int, is_personal: bool) -> RunContext[TelegramDeps]:
        deps = TelegramDeps(is_personal=is_personal, chat_info=ConversationInfo(credits=credits))
        return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), conversation_id='42')

    async def test_group_chat_run_drops_the_shop(self) -> None:
        roster = CreditGatedSubAgents(agents=[build_vkusvill_expert()], min_credits=2000)
        run = await roster.for_run(self.make_ctx(credits=50_000, is_personal=False))
        self.assertEqual(run.agents, [])

    async def test_poor_personal_chat_drops_the_shop(self) -> None:
        roster = CreditGatedSubAgents(agents=[build_vkusvill_expert()], min_credits=2000)
        run = await roster.for_run(self.make_ctx(credits=1999, is_personal=True))
        self.assertEqual(run.agents, [])

    async def test_rich_personal_chat_keeps_the_shop(self) -> None:
        roster = CreditGatedSubAgents(agents=[build_vkusvill_expert()], min_credits=2000)
        run = await roster.for_run(self.make_ctx(credits=2001, is_personal=True))
        self.assertEqual([a.name for a in run.agents], [VKUSVILL_EXPERT_NAME])


class BasketMemoTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_ctx(chat_id: int = 777):
        return SimpleNamespace(deps=SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id=chat_id))))

    async def test_products_and_cart_land_in_the_conversation_memo(self) -> None:
        from kibernikto.ai.agent.vkusvill.memory import basket_note, clear_basket, remember_basket

        ctx = self.make_ctx()
        clear_basket(ctx.deps)

        async def call_tool(name, args, *, metadata=None):
            if name == 'vkusvill_products_search':
                return json.dumps({'ok': True, 'data': {'items': [{'id': 5, 'name': 'Круассан&nbsp;на масле'}]}})
            return json.dumps({'ok': True, 'data': {'link': 'https://vkusvill.ru/mobile?basket&share=1'}})

        await remember_basket(ctx, call_tool, 'vkusvill_products_search', {'q': 'круассан'})
        await remember_basket(ctx, call_tool, 'vkusvill_cart_link_create', {'products': [{'id': 5, 'q': 2}]})

        note = basket_note(ctx.deps)
        self.assertIn('Круассан на масле × 2', note)
        self.assertIn('share=1', note)
        self.assertIn('предыдущую корзину не открывай', note)

    async def test_conversations_do_not_leak_baskets(self) -> None:
        from kibernikto.ai.agent.vkusvill.memory import basket_note, clear_basket, remember_basket

        owner = self.make_ctx(chat_id=888)
        stranger = self.make_ctx(chat_id=999)
        clear_basket(owner.deps)

        async def call_tool(name, args, *, metadata=None):
            return json.dumps({'ok': True, 'data': {'link': 'https://vkusvill.ru/mobile?basket&share=7'}})

        await remember_basket(owner, call_tool, 'vkusvill_cart_link_create', {'products': [{'id': 1, 'q': 1}]})

        self.assertIn('share=7', basket_note(owner.deps))
        self.assertEqual(basket_note(stranger.deps), '')

    def test_conversation_key_falls_back_to_user_id(self) -> None:
        from kibernikto.ai.agent.vkusvill.memory import conversation_key

        self.assertEqual(conversation_key(SimpleNamespace(message=None, user_id=42)), '42')
        self.assertIsNone(conversation_key(SimpleNamespace(message=None, user_id=None)))
