"""Per-chat notebooks of the business and travel experts, scoped like the VkusVill one."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import FunctionToolset, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai_harness.memory import InMemoryStore

from kibernikto.ai.agent.addons.business.agent import BUSINESS_EXPERT_NAME, build_business_expert
from kibernikto.ai.agent.addons.travel.agent import TRAVEL_EXPERT_NAME, build_travel_expert
from kibernikto.ai.agent.harness import expert_memory as em
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.storage.chat_wipe import wipe_chat


def deps_for(chat_id: int) -> TelegramDeps:
    return TelegramDeps(message=SimpleNamespace(chat=SimpleNamespace(id=chat_id)))


def writer_model(note: str) -> FunctionModel:
    """Writes one note on the first turn, then answers."""
    def respond(messages, info):
        if any(part.part_kind == 'tool-return' for m in messages for part in m.parts):
            return ModelResponse(parts=[TextPart('ok')])
        return ModelResponse(parts=[ToolCallPart('write_memory', {'content': note})])
    return FunctionModel(respond)


class ExpertMemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.store = InMemoryStore()
        patcher = patch.object(em, 'get_memory_store', return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_conversation_key_prefers_chat_then_user(self) -> None:
        self.assertEqual(em.conversation_key(deps_for(-100)), '-100')
        self.assertEqual(em.conversation_key(SimpleNamespace(message=None, user_id=42)), '42')
        self.assertIsNone(em.conversation_key(SimpleNamespace(message=None, user_id=None)))

    async def test_business_expert_writes_into_the_chat_notebook(self) -> None:
        expert = build_business_expert(model=writer_model('- наша компания ИНН 7700000000'),
                                       toolset=FunctionToolset())
        await expert.agent.run('привет', deps=deps_for(77), conversation_id='task-1')
        self.assertIn('77/business/MEMORY.md', await self.store.list_paths('', limit=50))

    async def test_travel_coordinator_writes_into_the_chat_notebook(self) -> None:
        expert = build_travel_expert(model=writer_model('- домашний аэропорт SVO'), experts=[])
        await expert.agent.run('привет', deps=deps_for(78), conversation_id='task-2')
        self.assertIn('78/travel/MEMORY.md', await self.store.list_paths('', limit=50))

    async def test_notebook_is_shared_across_delegated_tasks_of_one_chat(self) -> None:
        expert = build_travel_expert(model=writer_model('- любит прямые рейсы'), experts=[])
        await expert.agent.run('a', deps=deps_for(79), conversation_id='task-a')
        await expert.agent.run('b', deps=deps_for(79), conversation_id='task-b')
        self.assertEqual(len(await self.store.list_paths('79/travel/', limit=50)), 1)

    async def test_reset_wipes_expert_notebooks_of_that_chat_only(self) -> None:
        for path in ('5/business/MEMORY.md', '5/travel/MEMORY.md', '5/bot/MEMORY.md', '6/travel/MEMORY.md'):
            await self.store.write(path, 'fact\n', expected_version=None)
        removed = await wipe_chat(5, history=None, agent_name='bot', memory=self.store,
                                  expert_names=[BUSINESS_EXPERT_NAME, TRAVEL_EXPERT_NAME])
        self.assertEqual(removed, 3)
        self.assertEqual(await self.store.list_paths('', limit=50), ['6/travel/MEMORY.md'])

    def test_builders_register_their_notebooks_for_reset(self) -> None:
        build_business_expert(model=writer_model('x'), toolset=FunctionToolset())
        build_travel_expert(model=writer_model('x'), experts=[])
        self.assertLessEqual({BUSINESS_EXPERT_NAME, TRAVEL_EXPERT_NAME}, em.EXPERT_NOTEBOOKS)


if __name__ == '__main__':
    unittest.main()
