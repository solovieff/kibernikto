"""Persona template: {{name}} from the Telegram bot, {{traits}} from a source, plain text untouched, typos fail fast."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot
from aiogram.types import BotDescription, BotShortDescription, User
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.models.test import TestModel

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent
from kibernikto.ai.agent.core.persona import Persona, StaticPersona
from kibernikto.ai.agent.telegram import identity
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.identity import BotIdentity, fetch_bot_identity, set_bot_identity
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
from kibernikto.storage.config import STORAGE_SETTINGS

TEMPLATE = "You are {{name}} & co.\n{{#each traits}}{{@key}}: {{this}}\n{{/each}}sarcasm={{traits.sarcasm}}"


class FixedPersona:
    """Per-run source stand-in: proves values are read on every run, not baked at construction."""

    def __init__(self) -> None:
        self.persona = Persona(name='Wraith', traits={'sarcasm': 10})

    async def get(self, deps: object) -> Persona:
        return self.persona


async def first_instructions(agent: Agent, deps: object = None) -> str:
    """One offline run; returns the rendered instructions the model saw."""
    with capture_run_messages() as messages, agent.override(model=TestModel(call_tools=[])):
        await agent.run('hi', deps=deps)
    return messages[0].instructions or ''


class PersonaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = patch.object(STORAGE_SETTINGS, 'FILESTORE_LOCATION', self.dir.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        set_bot_identity(None)
        self.addCleanup(set_bot_identity, None)

    def write_persona(self, name: str, text: str) -> None:
        (Path(self.dir.name) / f'{name}-instructions.txt').write_text(text, encoding='utf-8')

    async def test_template_renders_source_values_each_run_without_html_escaping(self) -> None:
        self.write_persona('p1', TEMPLATE)
        source = FixedPersona()
        agent = build_kibernikto_agent(name='p1', history_storage=None, persona_source=source)
        self.assertIn('You are Wraith & co.\nsarcasm: 10\nsarcasm=10', await first_instructions(agent))
        source.persona = Persona(name='Shade', traits={'sarcasm': 2})
        self.assertIn('You are Shade & co.\nsarcasm: 2\nsarcasm=2', await first_instructions(agent))

    async def test_telegram_name_comes_from_bot_identity_and_env_override_wins(self) -> None:
        self.write_persona('p2', 'You are {{name}}.')
        agent = TelegramAgent(name='p2', history_storage=None)
        self.assertIn('You are Kibernikto.', await first_instructions(agent, TelegramDeps()))
        set_bot_identity(BotIdentity(username='cyber_bot', full_name='Кибер Никто'))
        self.assertIn('You are Кибер Никто.', await first_instructions(agent, TelegramDeps()))
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'PERSONA_NAME', 'Override'):
            self.assertIn('You are Override.', await first_instructions(agent, TelegramDeps()))

    async def test_static_traits_come_from_env_settings(self) -> None:
        self.write_persona('p3', 'joy={{traits.joy}} missing=[{{traits.nope}}]')
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'PERSONA_TRAITS', {'joy': 3}):
            agent = build_kibernikto_agent(name='p3', history_storage=None, persona_source=StaticPersona(name='K'))
            self.assertIn('joy=3 missing=[]', await first_instructions(agent))

    async def test_plain_text_persona_is_unchanged_and_falls_back_to_who_am_i(self) -> None:
        self.write_persona('p4', 'Plain persona, no templates.')
        prompt = await first_instructions(build_kibernikto_agent(name='p4', history_storage=None))
        self.assertTrue(prompt.startswith('Plain persona, no templates.\n\nCurrent date: '), prompt)
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'WHO_AM_I', 'Env persona {{name}}.'):
            agent = build_kibernikto_agent(name='absent', history_storage=None, persona_source=StaticPersona(name='E'))
        self.assertIn('Env persona E.', await first_instructions(agent))

    def test_unknown_template_field_fails_at_construction(self) -> None:
        self.write_persona('p5', 'You are {{nmae}}.')
        with self.assertRaisesRegex(Exception, 'nmae'):
            build_kibernikto_agent(name='p5', history_storage=None)

    async def test_escaped_braces_stay_literal(self) -> None:
        self.write_persona('p7', r'Answer as \{{answer}}, you are {{name}}.')
        agent = build_kibernikto_agent(name='p7', history_storage=None, persona_source=StaticPersona(name='K'))
        self.assertIn('Answer as {{answer}}, you are K.', await first_instructions(agent))

    async def test_template_switch_off_keeps_braces_literal_and_never_fails(self) -> None:
        self.write_persona('p8', 'Format: {{answer}} {{nmae}}')
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'PERSONA_TEMPLATE', False):
            prompt = await first_instructions(build_kibernikto_agent(name='p8', history_storage=None))
        self.assertTrue(prompt.startswith('Format: {{answer}} {{nmae}}\n\nCurrent date: '), prompt)

    async def test_identity_prompt_uses_telegram_display_name(self) -> None:
        set_bot_identity(BotIdentity(username='cyber_bot', full_name='Кибер Никто', short_description='тень'))
        prompt = await first_instructions(TelegramAgent(name='p6', history_storage=None), TelegramDeps())
        self.assertIn('[Your Telegram bot parameters] username: @cyber_bot | display_name: Кибер Никто | '
                      'short_description: тень', prompt)
        self.assertEqual(BotIdentity().as_prompt(), '')


class FetchBotIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_reads_get_me_and_tolerates_description_failures(self) -> None:
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        me = User(id=100, is_bot=True, first_name='Кибер', last_name='Никто', username='cyber_bot')
        short = AsyncMock(return_value=BotShortDescription(short_description='тень'))
        with patch.object(Bot, 'get_me', AsyncMock(return_value=me)), \
                patch.object(Bot, 'get_my_short_description', short), \
                patch.object(Bot, 'get_my_description', AsyncMock(side_effect=RuntimeError('boom'))), \
                self.assertLogs(identity.logger, 'WARNING'):
            got = await fetch_bot_identity(bot)
        self.assertEqual(got, BotIdentity(username='cyber_bot', full_name='Кибер Никто', short_description='тень'))
        empty = AsyncMock(return_value=BotShortDescription(short_description=''))
        with patch.object(Bot, 'get_me', AsyncMock(return_value=me)), \
                patch.object(Bot, 'get_my_short_description', empty), \
                patch.object(Bot, 'get_my_description', AsyncMock(return_value=BotDescription(description='long'))):
            got = await fetch_bot_identity(bot)
        self.assertEqual((got.short_description, got.description), (None, 'long'))


if __name__ == '__main__':
    unittest.main()
