"""Offline chat-memory regressions: per-chat notebook isolation, injection, full-history recall, backend choice."""

import os
import tempfile
import unittest
from unittest.mock import patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_harness.conversation_search import ConversationSearch
from pydantic_ai_harness.memory import FileStore, InMemoryStore, Memory, SqliteMemoryStore

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent
from kibernikto.ai.agent.harness.chat_memory import chat_memory
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
from kibernikto.storage import factory
from kibernikto.storage.base import MemoryHistoryStorage
from kibernikto.storage.sql.memory import asyncpg_dsn


class ScriptedModel:
    """Calls the tool named in the prompt (`tool:<name>:<arg>`) once, then answers; records every request."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        self.requests.append(last)
        prompt = next((p.content for p in last.parts if p.part_kind == 'user-prompt'), None)
        if isinstance(prompt, list):
            prompt = prompt[0]
        if isinstance(prompt, str) and prompt.startswith('tool:'):
            _, name, arg = prompt.split(':', 2)
            key = 'content' if name == 'write_memory' else 'query'
            return ModelResponse(parts=[ToolCallPart(name, {key: arg})])
        return ModelResponse(parts=[TextPart('ok')])

    def tool_returns(self) -> list[str]:
        return [str(p.content) for p in self.requests[-1].parts if p.part_kind == 'tool-return']


class ChatMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = InMemoryStore()
        self.history = MemoryHistoryStorage(history_size=2)
        self.model = ScriptedModel()
        self.agent = TelegramAgent(model=FunctionModel(self.model), name='mem-test', history_storage=self.history,
                                   capabilities=chat_memory('mem-test', store=self.store, history=self.history))

    async def say(self, conversation_id: int | str, text: str) -> None:
        await self.agent.run(text, conversation_id=str(conversation_id), deps=TelegramDeps())

    async def test_notebook_is_scoped_to_chat_and_injected_only_there(self) -> None:
        await self.say(5, 'tool:write_memory:- likes cats')
        self.assertEqual(dict(self.store.files), {'5/mem-test/MEMORY.md': '- likes cats\n'})
        await self.say(5, 'hello')
        self.assertIn('likes cats', repr(self.model.requests[-1]))
        await self.say(6, 'hello')
        self.assertNotIn('likes cats', repr(self.model.requests[-1]))

    async def test_persona_precedes_memory_guidance(self) -> None:
        # Plain persona is a static string, the case where stock capability guidance used to jump ahead of it.
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'WHO_AM_I', 'PERSONA-MARK'):
            agent = TelegramAgent(model=FunctionModel(self.model), name='mem-order', history_storage=self.history,
                                  capabilities=chat_memory('mem-order', store=self.store, history=self.history))
        await agent.run('hello', conversation_id='5', deps=TelegramDeps())
        instructions = self.model.requests[-1].instructions or ''
        self.assertTrue(instructions.startswith('PERSONA-MARK'), instructions[:120])
        self.assertIn('## Conversation memory', instructions)

    async def test_orchestrator_instructions_start_with_persona(self) -> None:
        # Plain and templated personas: a template is a callable, which pydantic_ai sorts after static text.
        for persona, rendered in (('PERSONA-MARK', 'PERSONA-MARK'), ('PERSONA-MARK {{name}}', 'PERSONA-MARK Kib')):
            with self.subTest(persona=persona), patch.object(AGENT_KIBERNIKTO_SETTINGS, 'WHO_AM_I', persona), \
                    patch.object(AGENT_KIBERNIKTO_SETTINGS, 'PERSONA_NAME', 'Kib'):
                parent = build_multi_agent()
                with parent.override(model=FunctionModel(self.model)):
                    await parent.run('hello', conversation_id='5', deps=TelegramDeps())
                instructions = self.model.requests[-1].instructions or ''
                self.assertTrue(instructions.startswith(rendered), instructions[:120])
                self.assertEqual(instructions.count('PERSONA-MARK'), 1)
                for guidance in ('## Conversation memory', 'search_conversation_history', 'delegate_task'):
                    self.assertIn(guidance, instructions)

    async def test_injected_memory_is_not_persisted_into_history(self) -> None:
        await self.say(5, 'tool:write_memory:- likes cats')
        await self.say(5, 'hello')
        self.assertNotIn('<memory>', repr(await self.history.get_full_conversation('5')))

    async def test_search_reaches_beyond_window_and_stays_in_chat(self) -> None:
        await self.say(6, 'pineapple is my password')
        await self.say(5, 'my dog is called Rex')
        for i in range(4):
            await self.say(5, f'filler {i}')
        await self.say(5, 'tool:search_conversation_history:Rex')
        self.assertIn('my dog is called Rex', self.model.tool_returns()[0])
        await self.say(5, 'tool:search_conversation_history:pineapple')
        self.assertNotIn('pineapple is my password', self.model.tool_returns()[0])

    async def test_guidance_tells_model_the_snapshot_is_not_from_the_user(self) -> None:
        await self.say(5, 'hello')
        self.assertIn('The user did not write it', self.model.requests[-1].instructions)

    async def test_works_on_a_plain_kibernikto_agent_without_telegram(self) -> None:
        agent = build_kibernikto_agent(model=FunctionModel(self.model), name='mem-core', history_storage=self.history,
                                deps_type=KiberniktoDeps,
                                capabilities=chat_memory('mem-core', store=self.store, history=self.history))
        await agent.run('tool:write_memory:- likes cats', conversation_id='5', deps=KiberniktoDeps())
        self.assertEqual(dict(self.store.files), {'5/mem-core/MEMORY.md': '- likes cats\n'})
        await agent.run('tool:search_conversation_history:cats', conversation_id='5', deps=KiberniktoDeps())
        self.assertIn('likes cats', self.model.tool_returns()[0])

    async def test_conversation_memory_class_capability(self) -> None:
        from kibernikto.ai.agent.harness.conversation_memory import ConversationMemory
        mem = ConversationMemory('mem-cls', store=self.store, history=self.history)
        agent = TelegramAgent(model=FunctionModel(self.model), name='mem-cls', history_storage=self.history,
                              capabilities=[mem])
        await agent.run('tool:write_memory:- likes dogs', conversation_id='10', deps=TelegramDeps())
        self.assertEqual(dict(self.store.files), {'10/mem-cls/MEMORY.md': '- likes dogs\n'})
        await agent.run('hello', conversation_id='10', deps=TelegramDeps())
        self.assertIn('likes dogs', repr(self.model.requests[-1]))

    async def test_orchestrator_parent_carries_memory_and_search(self) -> None:
        capabilities = build_multi_agent().root_capability.capabilities
        self.assertEqual(len([c for c in capabilities if isinstance(c, Memory)]), 1)
        self.assertEqual(len([c for c in capabilities if isinstance(c, ConversationSearch)]), 1)


class MemoryBackendTests(unittest.TestCase):
    def tearDown(self) -> None:
        factory._memory_store = factory._memory_pool = None

    def test_backend_follows_data_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for backend, expected in (('file', FileStore), ('sqlite', SqliteMemoryStore)):
                factory._memory_store = None
                with self.subTest(backend=backend), patch.multiple(
                        factory.STORAGE_SETTINGS, DATA_BACKEND=backend, FILESTORE_LOCATION=tmp,
                        SQLITE_PATH=f'{tmp}/bot.db'):
                    self.assertIsInstance(factory.get_memory_store(), expected)

    def test_pg_dsn_drops_sqlalchemy_driver(self) -> None:
        self.assertEqual(asyncpg_dsn('postgresql+asyncpg://u:p@h:5432/db'), 'postgresql://u:p@h:5432/db')


@unittest.skipUnless(os.getenv('KIBERNIKTO_TEST_PG_DSN'), 'set KIBERNIKTO_TEST_PG_DSN to run against a live PostgreSQL')
class PostgresMemoryTests(unittest.IsolatedAsyncioTestCase):
    """Live round trip through PostgresMemoryStore on a throwaway table; dropped afterwards."""

    TABLE = 'agent_memory_unittest'

    async def asyncSetUp(self) -> None:
        from pydantic_ai_harness.memory import PostgresMemoryStore

        from kibernikto.storage.sql.memory import LazyAsyncpgPool
        self.pool = LazyAsyncpgPool(os.environ['KIBERNIKTO_TEST_PG_DSN'])
        self.model = ScriptedModel()
        history = MemoryHistoryStorage()
        self.agent = TelegramAgent(model=FunctionModel(self.model), name='pg-test', history_storage=history,
                                   capabilities=chat_memory('pg-test', history=history,
                                                            store=PostgresMemoryStore(self.pool, table=self.TABLE)))

    async def asyncTearDown(self) -> None:
        async with self.pool.acquire() as connection:
            for table in (self.TABLE, f'{self.TABLE}_operations', f'{self.TABLE}_metadata'):
                await connection.execute(f'DROP TABLE IF EXISTS {table}')
            await connection.execute(f'DROP SEQUENCE IF EXISTS {self.TABLE}_versions')
        await self.pool.close()

    async def test_notebook_persists_per_chat_in_postgres(self) -> None:
        await self.agent.run('tool:write_memory:- likes cats', conversation_id='5', deps=TelegramDeps())
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(f'SELECT path, content FROM {self.TABLE}')
        self.assertEqual([tuple(r) for r in rows], [('5/pg-test/MEMORY.md', '- likes cats\n')])
        await self.agent.run('hello', conversation_id='5', deps=TelegramDeps())
        self.assertIn('likes cats', repr(self.model.requests[-1]))
        await self.agent.run('hello', conversation_id='6', deps=TelegramDeps())
        self.assertNotIn('likes cats', repr(self.model.requests[-1]))


if __name__ == '__main__':
    unittest.main()
