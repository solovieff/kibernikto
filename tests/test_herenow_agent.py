"""here.now expert: chat labels, routing without a local registry, tool errors and opt-in loading."""
import importlib
import os
import unittest
from unittest.mock import patch

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic import SecretStr
from pydantic_ai import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from kibernikto.ai.agent.addons.herenow.address import label_for_chat
from kibernikto.ai.agent.addons.herenow.client import HereNowClient, HereNowError, PublishedSite, SiteFile
from kibernikto.ai.agent.addons.herenow.config import HereNowSettings
from kibernikto.ai.agent.addons.herenow.routing import (
    chat_label,
    delete_for_chat,
    publish_for_chat,
    site_for_chat,
)
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent
from kibernikto.ai.agent.addons.travel.config import TRAVEL_SETTINGS
from kibernikto.ai.agent.addons.vkusvill.config import VKUSVILL_SETTINGS

PAGE_HTML = ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width, initial-scale=1">'
             '<style>h1{color:#333}</style></head><body><h1>привет</h1></body></html>')
PAGE = [SiteFile(path='index.html', content=PAGE_HTML)]


def herenow_agent():
    return importlib.import_module('kibernikto.ai.agent.addons.herenow.agent')


class FakeClient:
    """In-memory here.now: labels are the routing table, slugs are minted like the provider does."""

    def __init__(self, labels: dict | None = None) -> None:
        self.label_records = labels or {}
        self.published: list[tuple[str | None, list[SiteFile], str | None]] = []
        self.assigned: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.deleted_sites: list[str] = []
        self.opened: list[str] = []
        self.patched: list[tuple[str, dict]] = []
        self.update_error: HereNowError | None = None
        self.publish_error: HereNowError | None = None
        self.gone: set[str] = set()
        self._minted = 0

    async def labels(self) -> dict:
        return dict(self.label_records)

    async def assign_label(self, label: str, slug: str) -> dict:
        # The provider allows one active label per site and rejects a second one.
        if any(r.get('slug') == slug for r in self.label_records.values()):
            raise HereNowError('conflict', 'Site already has an active workspace label.')
        self.assigned.append((label, slug))
        self.label_records[label] = {'label': label, 'slug': slug, 'status': 'active',
                                     'url': f'https://{label}.kibernikto.here.now'}
        return self.label_records[label]

    async def delete_label(self, label: str) -> None:
        self.deleted.append(label)
        self.label_records.pop(label, None)

    async def publish(self, files: list[SiteFile], *, slug: str | None = None, title: str | None = None,
                      base_version_id: str | None = None) -> PublishedSite:
        self.published.append((slug, files, title))
        if self.publish_error is not None:
            raise self.publish_error
        if slug and self.update_error is not None:
            raise self.update_error
        if slug is None:
            self._minted += 1
            slug = f'site{self._minted}'
            auto = (title or slug).strip().lower().replace(' ', '-')  # new sites get a title-derived label
            self.label_records[auto] = {'label': auto, 'slug': slug, 'status': 'active',
                                        'url': f'https://{auto}.kibernikto.here.now'}
        return PublishedSite(slug=slug, url=f'https://{slug}.here.now/', version_id='v1')

    async def site(self, slug: str) -> dict:
        if slug in self.gone:
            raise HereNowError('http_404', 'site not found')
        return {'slug': slug, 'siteUrl': f'https://{slug}.here.now/', 'currentVersionId': 'v1'}

    async def file_text(self, slug: str, path: str = 'index.html') -> str:
        if slug in self.gone:
            raise HereNowError('http_404', 'site not found')
        return PAGE_HTML

    async def delete_site(self, slug: str) -> None:
        # The provider drops the label together with the site.
        self.deleted_sites.append(slug)
        self.gone.add(slug)
        for label, record in list(self.label_records.items()):
            if record.get('slug') == slug:
                self.label_records.pop(label, None)

    async def set_access(self, slug: str, mode: str = 'anyone_with_link') -> dict:
        if slug in self.gone:
            raise HereNowError('http_404', 'site not found')
        self.opened.append(slug)
        return {'mode': mode}

    async def patch_metadata(self, slug: str, *, title: str | None = None, password: str | None = None) -> dict:
        self.patched.append((slug, {'title': title, 'password': password}))
        return {'success': True}


class HereNowTests(unittest.IsolatedAsyncioTestCase):
    def test_labels_are_readable_and_dns_safe(self):
        cases = {
            ('gosu', 42): 'gosu',
            (None, 42): 'u42',
            ('Госу', 42): 'u42',
            ('--x--', 7): 'u7',  # single-character labels are outside the workspace pattern
            ('a' * 80, 1): 'a' * 63,
            ('Foo Bar', 5): 'foo-bar',
            (None, None): 'u0',
            ('.', -100123): 'u100123',
        }
        for (username, chat_id), expected in cases.items():
            with self.subTest(username=username, chat_id=chat_id):
                self.assertEqual(label_for_chat(username, chat_id), expected)

    def test_expert_is_opt_in_and_needs_a_key(self):
        with patch.dict(os.environ, {}, clear=False) as env:  # ambient AGENT_HERENOW_* must not leak in
            for name in [name for name in env if name.startswith('AGENT_HERENOW_')]:
                del env[name]
            self.assertFalse(HereNowSettings(_env_file=None).active)
            self.assertFalse(HereNowSettings(_env_file=None, ENABLED=True).active)
            self.assertFalse(HereNowSettings(_env_file=None, ENABLED=True, API_KEY=SecretStr('  ')).active)
            self.assertIsNone(HereNowSettings(_env_file=None, API_KEY=SecretStr('')).key)
        keyed = HereNowSettings(_env_file=None, ENABLED=True, API_KEY=SecretStr('demo-key'))
        self.assertTrue(keyed.active)
        self.assertNotIn('demo-key', repr(keyed))

    def test_workspace_and_auth_headers_are_never_in_the_url(self):
        client = HereNowClient(HereNowSettings(_env_file=None, API_KEY=SecretStr('demo-key'), WORKSPACE='kibernikto'))
        headers = client._headers()
        self.assertEqual(headers['Authorization'], 'Bearer demo-key')
        self.assertEqual(headers['X-HereNow-Account'], 'kibernikto')
        self.assertEqual(headers['X-HereNow-Client'], 'kibernikto')
        session = client._session()
        self.assertEqual(str(session.base_url), 'https://here.now')
        self.assertNotIn('demo-key', str(client._session().base_url))

    def test_limits_reject_before_http(self):
        client = HereNowClient(HereNowSettings(_env_file=None, MAX_FILES=2, MAX_TOTAL_BYTES=100))
        bad_sites = {
            'empty_site': [],
            'missing_index': [SiteFile(path='about.html', content='x')],
            'bad_path': [SiteFile(path='index.html', content='x'), SiteFile(path='/etc/passwd', content='x')],
        }
        for code, files in bad_sites.items():
            with self.subTest(code=code):
                with self.assertRaises(HereNowError) as caught:
                    client._check_limits(files)
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(HereNowError) as too_many:
            client._check_limits([SiteFile(path='index.html', content='x')] + PAGE * 2)
        self.assertEqual(too_many.exception.code, 'too_many_files')
        with self.assertRaises(HereNowError) as too_big:
            client._check_limits([SiteFile(path='index.html', content='x' * 200)])
        self.assertEqual(too_big.exception.code, 'site_too_large')

    async def test_first_publish_replaces_the_auto_label(self):
        client = FakeClient()
        site = await self._publish(client, TelegramDeps(user_id=42, username='gosu'))
        self.assertEqual(site.slug, 'site1')
        self.assertEqual(site.label_url, 'https://gosu.kibernikto.here.now')
        self.assertEqual(client.deleted, ['t'])  # title-derived label from the publish
        self.assertEqual(client.assigned, [('gosu', 'site1')])
        self.assertEqual(client.opened, ['site1'])  # a new site must be opened to readers

    async def test_second_publish_updates_the_same_slug(self):
        client = FakeClient()
        await self._publish(client, TelegramDeps(user_id=42, username='gosu'))
        site = await self._publish(client, TelegramDeps(user_id=42, username='gosu'))
        self.assertEqual(site.slug, 'site1')
        self.assertEqual([slug for slug, _, _ in client.published], [None, 'site1'])
        self.assertEqual(len(client.assigned), 1)
        self.assertEqual(client.deleted, ['t'])
        self.assertEqual(client.opened, ['site1'])  # updates never touch the visitor policy
        self.assertEqual(set(client.label_records), {'gosu'})

    async def test_stale_label_publishes_a_new_site(self):
        client = FakeClient()
        await self._publish(client, TelegramDeps(user_id=42, username='gosu'))
        client.update_error = HereNowError('http_404', 'site not found')
        client.gone.add('site1')
        with self.assertLogs('kibernikto.ai.agent.addons.herenow.routing', level='WARNING'):
            site = await self._publish(client, TelegramDeps(user_id=42, username='gosu'))
        self.assertEqual(site.slug, 'site2')
        self.assertEqual(site.label_url, 'https://gosu.kibernikto.here.now')
        self.assertEqual(client.assigned[-1], ('gosu', 'site2'))
        self.assertEqual(client.label_records['gosu']['slug'], 'site2')

    async def test_label_claim_failure_keeps_the_site(self):
        client = FakeClient()

        async def refuse(label: str, slug: str) -> dict:
            raise HereNowError('invalid_label', 'label is taken')

        client.assign_label = refuse
        with self.assertLogs('kibernikto.ai.agent.addons.herenow.routing', level='WARNING'):
            site = await self._publish(client, TelegramDeps(user_id=42, username='gosu'))
        self.assertEqual(site.url, 'https://site1.here.now/')
        self.assertIsNone(site.label_url)

    def test_chat_without_username_falls_back_to_chat_id(self):
        self.assertEqual(chat_label(TelegramDeps(user_id=555)), 'u555')

    async def test_site_for_chat_is_empty_before_the_first_publish(self):
        label, slug, site = await site_for_chat(FakeClient(), TelegramDeps(user_id=42, username='gosu'))
        self.assertEqual((label, slug, site), ('gosu', None, None))

    async def test_version_conflict_is_reported_as_text(self):
        agent_module = herenow_agent()
        client = FakeClient()
        client.publish_error = HereNowError('version_conflict', 'stale base version')
        expert = agent_module.build_herenow_expert(
            model=self._model('publish_site', {'files': [{'path': 'index.html', 'content': PAGE_HTML}]}), client=client)
        result = await expert.agent.run('сделай сайт', deps=TelegramDeps(user_id=42, username='gosu'))
        self.assertIn('elsewhere', result.output)
        self.assertIn('Re-read', result.output)

    async def test_tool_reports_error_codes_without_raising(self):
        agent_module = herenow_agent()
        client = FakeClient()
        client.publish_error = HereNowError('workspace_not_ready', 'provisioning')
        expert = agent_module.build_herenow_expert(
            model=self._model('publish_site', {'files': [{'path': 'index.html', 'content': PAGE_HTML}]}), client=client)
        result = await expert.agent.run('сделай сайт', deps=TelegramDeps(user_id=42))
        self.assertIn('in a minute', result.output)

    async def test_update_meta_without_a_site_explains_instead_of_calling(self):
        agent_module = herenow_agent()
        client = FakeClient()
        expert = agent_module.build_herenow_expert(
            model=self._model('update_site_meta', {'title': 'Визитка'}), client=client)
        result = await expert.agent.run('поставь название', deps=TelegramDeps(user_id=42))
        self.assertIn('no site yet', result.output)
        self.assertEqual(client.patched, [])

    async def test_access_failure_does_not_block_the_publish(self):
        client = FakeClient()

        async def refuse(slug: str, mode: str = 'anyone_with_link') -> dict:
            raise HereNowError('http_403', 'not owner')

        client.set_access = refuse
        with self.assertLogs('kibernikto.ai.agent.addons.herenow.routing', level='WARNING'):
            site = await self._publish(client, TelegramDeps(user_id=42, username='gosu'))
        self.assertEqual(site.label_url, 'https://gosu.kibernikto.here.now')

    async def test_publish_tool_returns_a_bare_url(self):
        agent_module = herenow_agent()
        client = FakeClient()
        expert = agent_module.build_herenow_expert(
            model=self._model('publish_site', {'files': [{'path': 'index.html', 'content': PAGE_HTML}]}),
            client=client)
        result = await expert.agent.run('сделай сайт', deps=TelegramDeps(user_id=42, username='gosu'))
        self.assertEqual(result.output.splitlines()[-1], 'https://gosu.kibernikto.here.now')
        self.assertEqual(client.published[0][1][0].content_type, 'text/html; charset=utf-8')

    async def test_truncated_page_is_rejected_before_any_request(self):
        agent_module = herenow_agent()
        client = FakeClient()
        broken = PAGE_HTML[:PAGE_HTML.index('</body>')]  # mid-page cut, exactly what a token cap produces
        expert = agent_module.build_herenow_expert(
            model=self._model('publish_site', {'files': [{'path': 'index.html', 'content': broken}]}), client=client)
        result = await expert.agent.run('сделай сайт', deps=TelegramDeps(user_id=42, username='gosu'))
        self.assertIn('failed the checks', result.output)
        self.assertIn('truncated', result.output)
        self.assertEqual(client.published, [])

    async def test_placeholder_text_is_rejected(self):
        agent_module = herenow_agent()
        client = FakeClient()
        stub = PAGE_HTML.replace('<h1>привет</h1>', '<h1>Lorem ipsum</h1>')
        expert = agent_module.build_herenow_expert(
            model=self._model('publish_site', {'files': [{'path': 'index.html', 'content': stub}]}), client=client)
        result = await expert.agent.run('сделай сайт', deps=TelegramDeps(user_id=42))
        self.assertIn('filler', result.output)
        self.assertEqual(client.published, [])

    async def test_read_site_returns_the_live_page(self):
        agent_module = herenow_agent()
        client = FakeClient()
        await self._publish(client, TelegramDeps(user_id=42, username='gosu'))
        expert = agent_module.build_herenow_expert(model=self._model('read_site', {}), client=client)
        result = await expert.agent.run('покажи сайт', deps=TelegramDeps(user_id=42, username='gosu'))
        self.assertIn('index.html of this chat', result.output)
        self.assertIn('<h1>привет</h1>', result.output)

    async def test_read_site_without_a_site_explains(self):
        expert = herenow_agent().build_herenow_expert(model=self._model('read_site', {}), client=FakeClient())
        result = await expert.agent.run('покажи сайт', deps=TelegramDeps(user_id=42))
        self.assertIn('no site yet', result.output)

    async def test_delete_removes_the_chat_site_and_frees_the_label(self):
        agent_module = herenow_agent()
        client = FakeClient()
        await self._publish(client, TelegramDeps(user_id=42, username='gosu'))
        expert = agent_module.build_herenow_expert(model=self._model('delete_site', {}), client=client)
        result = await expert.agent.run('удали сайт', deps=TelegramDeps(user_id=42, username='gosu'))
        self.assertEqual(client.deleted_sites, ['site1'])
        self.assertEqual(client.label_records, {})
        self.assertIn('Site deleted', result.output)

    async def test_delete_without_a_site_does_not_call_the_provider(self):
        agent_module = herenow_agent()
        client = FakeClient()
        expert = agent_module.build_herenow_expert(model=self._model('delete_site', {}), client=client)
        result = await expert.agent.run('удали сайт', deps=TelegramDeps(user_id=42))
        self.assertEqual(client.deleted_sites, [])
        self.assertIn('no site', result.output)

    async def test_delete_tolerates_a_site_that_is_already_gone(self):
        client = FakeClient({'gosu': {'label': 'gosu', 'slug': 'site1', 'status': 'active',
                                      'url': 'https://gosu.kibernikto.here.now'}})

        async def missing(slug: str) -> None:
            raise HereNowError('http_404', 'site not found')

        client.delete_site = missing
        self.assertEqual(await delete_for_chat(client, TelegramDeps(user_id=42, username='gosu')), 'site1')

    async def test_no_key_means_no_herenow_agent(self):
        with patch.object(TRAVEL_SETTINGS, 'ENABLED', False), \
             patch.object(VKUSVILL_SETTINGS, 'ENABLED', False):
            parent = build_multi_agent()
        from kibernikto.ai.agent.harness.delegation import (
            CreditGatedSubAgents,
            KiberniktoSubAgents,
        )
        found = []
        parent.root_capability.apply(
            lambda c: found.append(c) if isinstance(c, (KiberniktoSubAgents, CreditGatedSubAgents)) else None)
        names = {a.name for cap in found for a in cap.agents}
        self.assertNotIn('herenow', names)

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _publish(self, client: FakeClient, deps: TelegramDeps) -> PublishedSite:
        return await publish_for_chat(client, deps, PAGE, title='T')

    def _model(self, tool_name: str, arguments: dict) -> FunctionModel:
        def model(messages, info):
            returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
            if returns:
                return ModelResponse(parts=[TextPart(str(returns[-1].content))])
            return ModelResponse(parts=[ToolCallPart(tool_name, arguments)])
        return FunctionModel(model)
