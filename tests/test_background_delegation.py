"""Offline BackgroundDelegation: slow expert leaves the run, the report returns as a follow-up delivery."""

import asyncio
import os
import unittest
from collections.abc import AsyncIterator

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import Agent, ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_harness.subagents import DelegationTask, SubAgent

from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.harness.background import BACKGROUND_TASKS, BackgroundDelegation, background_of, report_prompt
from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents

RELEASE_AFTER = 0.05


def build(
        delivered: list[tuple[DelegationTask, KiberniktoDeps]], expert_delay: float, limit: int = 0,
) -> tuple[Agent, BackgroundDelegation]:
    async def expert_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        await asyncio.sleep(expert_delay)
        return ModelResponse(parts=[TextPart('expert result')])

    async def expert_stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        await asyncio.sleep(expert_delay)
        yield 'expert result'

    def parent_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returned = [p for m in messages for p in getattr(m, 'parts', ()) if isinstance(p, ToolReturnPart)]
        if returned:
            return ModelResponse(parts=[TextPart(f'got: {returned[-1].content}')])
        args = {'agent_name': 'slow', 'task': 'do it'}
        return ModelResponse(parts=[ToolCallPart('delegate_task', args)])

    async def deliver(task: DelegationTask, deps: KiberniktoDeps, binaries: list) -> None:
        delivered.append((task, deps))

    background = BackgroundDelegation(after=RELEASE_AFTER, deliver=deliver, limit=limit)
    expert = Agent(FunctionModel(expert_model, stream_function=expert_stream), name='slow', description='slow expert')
    roster = KiberniktoSubAgents(agents=[SubAgent(expert, name='slow')], agent_folders=None)
    agent = Agent(FunctionModel(parent_model), deps_type=KiberniktoDeps, capabilities=[roster, background])
    return agent, background


class BackgroundDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_inert_until_opened(self) -> None:
        delivered: list = []
        agent, background = build(delivered, expert_delay=0.15)
        result = await agent.run('go', deps=KiberniktoDeps(), conversation_id='c1')
        self.assertIn('expert result', result.output)  # Synchronous delegation, nothing backgrounded.
        self.assertEqual(delivered, [])
        self.assertIsNone(background.get_instructions())
        self.assertIs(background_of(agent), background)

    async def test_slow_expert_is_released_and_reported(self) -> None:
        delivered: list = []
        agent, background = build(delivered, expert_delay=0.3)
        deps = KiberniktoDeps()
        async with background.opened():
            result = await agent.run('go', deps=deps, conversation_id='c1')
            self.assertIn('running in the background', result.output)
            self.assertEqual(delivered, [])
            self.assertEqual(len(deps.extra[BACKGROUND_TASKS]), 1)  # Flagged for AgentReaction's slower throttle.
            await asyncio.wait_for(self._until(lambda: delivered), 3)
        task, origin = delivered[0]
        self.assertEqual((task.outcome, task.output, task.conversation_id), ('ok', 'expert result', 'c1'))
        self.assertIs(origin, deps)
        self.assertTrue(task.delivered)
        self.assertEqual(deps.extra[BACKGROUND_TASKS], set())  # Cleared once the task finished.
        self.assertIn('expert result', report_prompt(task))
        self.assertEqual(background._origins, {})  # Deps with attachments are not kept after the delivery.

    async def test_fast_expert_stays_synchronous(self) -> None:
        delivered: list = []
        agent, background = build(delivered, expert_delay=0.0)
        async with background.opened():
            result = await agent.run('go', deps=KiberniktoDeps(), conversation_id='c1')
            self.assertEqual(background._origins, {})  # Nothing left behind by a finished synchronous run.
        self.assertIn('expert result', result.output)
        self.assertEqual(delivered, [])

    async def test_origin_is_kept_while_a_task_runs_in_background(self) -> None:
        delivered: list = []
        agent, background = build(delivered, expert_delay=0.3)
        async with background.opened():
            await agent.run('go', deps=KiberniktoDeps(), conversation_id='c1')
            self.assertIn('c1', background._origins)  # The report still needs the run's deps.
            await asyncio.wait_for(self._until(lambda: delivered), 3)
        self.assertEqual(background._origins, {})

    async def test_chat_over_the_limit_waits_for_its_background_tasks(self) -> None:
        delivered: list = []
        agent, background = build(delivered, expert_delay=0.4, limit=1)
        async with background.opened():
            first = await agent.run('go', deps=KiberniktoDeps(), conversation_id='c1')
            self.assertIn('running in the background', first.output)
            second = await agent.run('again', deps=KiberniktoDeps(), conversation_id='c1')
            self.assertIn('already working in the background', second.output)  # Refused, not started.
            other = await agent.run('go', deps=KiberniktoDeps(), conversation_id='c2')
            self.assertIn('running in the background', other.output)  # Another chat has its own share.
            await asyncio.wait_for(self._until(lambda: len(delivered) == 2), 3)
            third = await agent.run('later', deps=KiberniktoDeps(), conversation_id='c1')
            self.assertIn('running in the background', third.output)  # Room again once the reports are in.
            await asyncio.wait_for(self._until(lambda: len(delivered) == 3), 3)

    async def test_run_without_conversation_is_never_backgrounded(self) -> None:
        delivered: list = []
        agent, background = build(delivered, expert_delay=0.15)
        async with background.opened():
            result = await agent.run('go', deps=KiberniktoDeps(), conversation_id='')  # Anonymous, as ConversationHistory makes it.
        self.assertIn('expert result', result.output)
        self.assertEqual(delivered, [])

    @staticmethod
    async def _until(condition) -> None:
        while not condition():
            await asyncio.sleep(0.01)


if __name__ == '__main__':
    unittest.main()
