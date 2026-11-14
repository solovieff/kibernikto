"""Travala hotel expert: search-only tools and anonymous OAuth client caching."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

import httpx2
from pydantic_ai import FunctionToolset, RunContext, RunUsage
from pydantic_ai.models.test import TestModel

from kibernikto.ai.agent.addons.travel.travala.agent import build_travala_expert, search_only_toolset
from kibernikto.ai.agent.addons.travel.travala.auth import TravalaAuth
from kibernikto.ai.agent.addons.travel.travala.config import TravalaSettings
from kibernikto.ai.agent.telegram.deps import TelegramDeps

REAL_CLIENT = httpx2.AsyncClient


class TravalaSettingsTests(unittest.TestCase):
    def test_defaults_and_env(self):
        self.assertEqual(TravalaSettings(_env_file=None).MCP_URL, 'https://travel-mcp.travala.com/mcp')
        with patch.dict(os.environ, {'AGENT_TRAVEL_TRAVALA_MAX_TOOL_CALLS': '7'}):
            self.assertEqual(TravalaSettings(_env_file=None).MAX_TOOL_CALLS, 7)

    def test_builds_offline(self):
        expert = build_travala_expert(settings=TravalaSettings(_env_file=None), model=TestModel())
        self.assertEqual(expert.name, 'travala')


class TravalaToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_search_tools_are_available(self):
        server = FunctionToolset()
        for name in ('travala_search_hotel', 'travala_search_package', 'travala_confirm_wallet_booking',
                     'travala_cancel_booking', 'travala_wallet_balance'):
            server.add_function(lambda: 'ok', name=name)
        toolset = search_only_toolset(server)
        ctx = RunContext(deps=TelegramDeps(), model=TestModel(), usage=RunUsage())
        async with toolset:
            self.assertEqual(set(await toolset.get_tools(ctx)), {'travala_search_hotel', 'travala_search_package'})


class TravalaAuthTests(unittest.IsolatedAsyncioTestCase):
    def make_auth(self, handler, path: Path) -> tuple[TravalaAuth, list[httpx2.Request]]:
        seen: list[httpx2.Request] = []

        def record(request: httpx2.Request) -> httpx2.Response:
            seen.append(request)
            return handler(request)

        transport = httpx2.MockTransport(record)
        patcher = patch('kibernikto.ai.agent.addons.travel.travala.auth.httpx2.AsyncClient',
                        lambda **kw: REAL_CLIENT(transport=transport, **kw))
        patcher.start()
        self.addCleanup(patcher.stop)
        return TravalaAuth(TravalaSettings(_env_file=None), client_path=path), seen

    async def test_registers_once_caches_client_and_reuses_token(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            if request.url.path == '/oauth/register':
                return httpx2.Response(201, json={'client_id': 'cid', 'client_secret': 'sec'})
            return httpx2.Response(200, json={'access_token': 'tok', 'expires_in': 3600})

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x' / 'client.json'
            auth, seen = self.make_auth(handler, path)
            self.assertEqual(await auth._bearer(), 'tok')
            self.assertEqual(await auth._bearer(), 'tok')
            self.assertEqual([r.url.path for r in seen], ['/oauth/register', '/oauth/token'])
            self.assertEqual(json.loads(path.read_text()), {'client_id': 'cid', 'client_secret': 'sec'})

            second, seen2 = self.make_auth(handler, path)
            await second._bearer()
            self.assertEqual([r.url.path for r in seen2], ['/oauth/token'])

    async def test_revoked_cached_client_is_re_registered(self):
        calls = {'token': 0}

        def handler(request: httpx2.Request) -> httpx2.Response:
            if request.url.path == '/oauth/register':
                return httpx2.Response(201, json={'client_id': 'new', 'client_secret': 'new'})
            calls['token'] += 1
            if calls['token'] == 1:
                return httpx2.Response(401, json={'error': 'invalid_client'})
            return httpx2.Response(200, json={'access_token': 'fresh', 'expires_in': 3600})

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'client.json'
            path.write_text(json.dumps({'client_id': 'old', 'client_secret': 'old'}))
            auth, _ = self.make_auth(handler, path)
            self.assertEqual(await auth._bearer(), 'fresh')
            self.assertEqual(json.loads(path.read_text())['client_id'], 'new')


if __name__ == '__main__':
    unittest.main()
