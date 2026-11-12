"""Offline coverage for the VkusVill MCP agent: settings, toolset wiring, behaviour prompt."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from fastmcp.client.auth import OAuth
from pydantic import ValidationError
from pydantic_ai import FunctionToolset, ModelMessage, ModelRequest, ModelResponse, TextPart
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.function import AgentInfo, FunctionModel

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.vkusvill.agent import build_vkusvill_agent
from kibernikto.ai.agent.vkusvill.config import (
    DEFAULT_MCP_URL,
    DEFAULT_SCOPES,
    VkusvillSettings,
    resolve_token_dir,
)
from kibernikto.ai.agent.vkusvill.mcp import build_vkusvill_toolset


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

    async def test_instructions_carry_the_shopping_contract(self) -> None:
        await self.agent.run('привет', deps=TelegramDeps())
        instructions = self.model.requests[-1].instructions or ''
        self.assertIn('ВкусВилл', instructions)
        self.assertIn('vkusvill_cart_link_create', instructions)
        self.assertIn('vkusvill.ru/mobile?basket&share=', instructions)
        self.assertIn('не оформляешь заказ', instructions)

    async def test_generic_persona_is_not_injected(self) -> None:
        await self.agent.run('привет', deps=TelegramDeps())
        instructions = self.model.requests[-1].instructions or ''
        self.assertNotIn('Kibernikto', instructions)
