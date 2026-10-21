"""Offline regressions for mid-run steering via agent.run(..., conversation_id=...)."""

import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot
from aiogram.methods import SendMessage, SetMessageReaction
from aiogram.types import Chat, Message, ReactionTypeEmoji, User
from pydantic_ai import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.messages import ImageUrl, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent
from kibernikto.ai.agent.harness.conversation_history import is_steered
from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
from kibernikto.storage.base import MemoryHistoryStorage


def _user_texts(messages: list[ModelMessage]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        for part in msg.parts:
            if isinstance(part, UserPromptPart):
                if isinstance(part.content, str):
                    out.append(part.content)
                elif isinstance(part.content, list):
                    out.extend(item for item in part.content if isinstance(item, str))
    return out


class SteeringTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_run_with_same_conversation_id_steers_mid_tool_and_returns_none(self) -> None:
        history = MemoryHistoryStorage(history_size=20)
        tool_started = asyncio.Event()
        release_tool = asyncio.Event()
        seen_steps: list[list[str]] = []

        async def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen_steps.append(_user_texts(messages))
            if len(seen_steps) == 1:
                return ModelResponse(parts=[ToolCallPart(tool_name='slow_tool', args={})])
            return ModelResponse(parts=[TextPart(content=' | '.join(seen_steps[-1]))])

        agent = build_kibernikto_agent(model=FunctionModel(model_fn), name='steer-tool',
                                history_storage=history, persona=False)

        @agent.tool_plain
        async def slow_tool() -> str:
            tool_started.set()
            await release_tool.wait()
            return 'tool_done'

        first_task = asyncio.create_task(agent.run('first message', conversation_id='chat-42'))
        await tool_started.wait()

        second_result = await agent.run('second message mid-tool', conversation_id='chat-42')
        self.assertTrue(is_steered(second_result))

        release_tool.set()
        first_result = await first_task
        self.assertIsNotNone(first_result)
        self.assertEqual(first_result.output, 'first message | second message mid-tool')

        stored = await history.get_full_conversation('chat-42')
        self.assertEqual(_user_texts(stored), ['first message', 'second message mid-tool'])
        self.assertTrue(all(m.conversation_id == 'chat-42' for m in stored))

    async def test_concurrent_run_steers_while_model_is_generating_without_tools(self) -> None:
        history = MemoryHistoryStorage(history_size=20)
        model_started = asyncio.Event()
        release_model = asyncio.Event()
        calls = 0

        async def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                model_started.set()
                await release_model.wait()
                return ModelResponse(parts=[TextPart(content='draft')])
            return ModelResponse(parts=[TextPart(content=' + '.join(_user_texts(messages)))])

        agent = build_kibernikto_agent(model=FunctionModel(model_fn), name='steer-direct',
                                history_storage=history, persona=False)

        first_task = asyncio.create_task(agent.run('part 1', conversation_id='chat-7'))
        await model_started.wait()

        second_result = await agent.run('part 2', conversation_id='chat-7')
        self.assertTrue(is_steered(second_result))

        release_model.set()
        first_result = await first_task
        self.assertIsNotNone(first_result)
        self.assertEqual(first_result.output, 'part 1 + part 2')
        self.assertEqual(calls, 2)

    async def test_different_conversation_ids_run_independently_in_parallel(self) -> None:
        history = MemoryHistoryStorage(history_size=20)
        both_started = asyncio.Barrier(2)

        async def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            await both_started.wait()
            return ModelResponse(parts=[TextPart(content=_user_texts(messages)[-1])])

        agent = build_kibernikto_agent(model=FunctionModel(model_fn), name='steer-isolated',
                                history_storage=history, persona=False)

        res_a, res_b = await asyncio.gather(
            agent.run('hello A', conversation_id='chat-A'),
            agent.run('hello B', conversation_id='chat-B'),
        )
        self.assertEqual(res_a.output, 'hello A')
        self.assertEqual(res_b.output, 'hello B')
        self.assertEqual(_user_texts(await history.get_full_conversation('chat-A')), ['hello A'])
        self.assertEqual(_user_texts(await history.get_full_conversation('chat-B')), ['hello B'])

    async def test_steered_run_merges_user_message_parts_into_active_deps(self) -> None:
        tool_started = asyncio.Event()
        release_tool = asyncio.Event()
        calls = 0

        async def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                return ModelResponse(parts=[ToolCallPart(tool_name='wait_for_photo', args={})])
            return ModelResponse(parts=[TextPart(content='done')])

        agent = build_kibernikto_agent(model=FunctionModel(model_fn), name='steer-deps',
                                history_storage=None, persona=False, deps_type=KiberniktoDeps)

        @agent.tool_plain
        async def wait_for_photo() -> str:
            tool_started.set()
            await release_tool.wait()
            return 'ready'

        deps1 = KiberniktoDeps(user_message_parts=['first text'])
        first_task = asyncio.create_task(agent.run('first text', conversation_id='chat-9', deps=deps1))
        await tool_started.wait()

        img = ImageUrl(url='https://example.com/cat.jpg')
        deps2 = KiberniktoDeps(user_message_parts=['second with photo', img])
        steered = await agent.run(['second with photo', img], conversation_id='chat-9', deps=deps2)
        self.assertTrue(is_steered(steered))

        release_tool.set()
        await first_task
        self.assertIn(img, deps1.user_message_parts)

    async def test_delegated_subagent_is_not_swallowed_by_parent_active_run(self) -> None:
        child = build_kibernikto_agent(
            model=FunctionModel(lambda m, i: ModelResponse(parts=[TextPart('child_answer')])),
            name='child-expert',
            description='helper',
            history_storage=None,
            persona=False,
        )
        calls = 0

        def parent_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'child-expert', 'task': 'help'})])
            return ModelResponse(parts=[TextPart('parent_done')])

        parent = build_kibernikto_agent(
            model=FunctionModel(parent_fn),
            name='parent',
            history_storage=MemoryHistoryStorage(),
            persona=False,
            capabilities=[KiberniktoSubAgents(agents=[SubAgent(child)], agent_folders=None)],
        )
        result = await parent.run('start', conversation_id='chat-100')
        self.assertEqual(result.output, 'parent_done')

    async def test_telegram_agent_replies_once_to_latest_steered_message(self) -> None:
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        bot.session.make_request = AsyncMock(return_value=True)

        model_started = asyncio.Event()
        release_model = asyncio.Event()
        calls = 0

        async def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                model_started.set()
                await release_model.wait()
                return ModelResponse(parts=[TextPart(content='first draft')])
            return ModelResponse(parts=[TextPart(content='combined answer')])

        tg_agent = TelegramAgent(
            model=FunctionModel(model_fn),
            name='tg-steer',
            history_storage=MemoryHistoryStorage(),
            persona=False,
            reaction='👀',
        )
        tg_agent.build_deps = AsyncMock(side_effect=lambda msg: tg_agent._deps_type(message=msg, is_personal=True))

        chat = Chat(id=500, type='private')
        user = User(id=500, is_bot=False, first_name='Alice')
        msg1 = Message(message_id=10, date=datetime.now(timezone.utc), chat=chat, from_user=user, text='hello').as_(bot)
        msg2 = Message(message_id=11, date=datetime.now(timezone.utc), chat=chat, from_user=user, text='wait also this').as_(bot)

        task1 = asyncio.create_task(tg_agent.process_message(msg1))
        await model_started.wait()

        res2 = await tg_agent.process_message(msg2)
        self.assertIsNone(res2)
        await tg_agent.reply_to(msg2, res2)

        release_model.set()
        res1 = await task1
        self.assertIsNotNone(res1)
        await tg_agent.reply_to(msg1, res1)

        reactions = [c.args[1] for c in bot.session.make_request.await_args_list if isinstance(c.args[1], SetMessageReaction)]
        self.assertEqual(len(reactions), 1)
        self.assertEqual(reactions[0].message_id, 10)
        self.assertEqual(reactions[0].reaction, [ReactionTypeEmoji(emoji='✍')])

        sent_methods = [c.args[1] for c in bot.session.make_request.await_args_list if isinstance(c.args[1], SendMessage)]
        self.assertEqual(len(sent_methods), 1)
        self.assertEqual(sent_methods[0].text, 'combined answer')
        self.assertEqual(sent_methods[0].reply_parameters.message_id, 11)


if __name__ == '__main__':
    unittest.main()
