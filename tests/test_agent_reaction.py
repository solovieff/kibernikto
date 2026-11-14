"""Offline AgentReaction regressions: parent and delegate emojis on the user's message, failures stay cosmetic."""

import asyncio
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SetMessageReaction
from aiogram.types import Chat, Message, ReactionTypeEmoji, User
from pydantic_ai import Agent, ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_harness.subagents import SubAgent

from kibernikto.config import APP_SETTINGS
from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents
from kibernikto.ai.agent.harness.image_agent import image_agent
from kibernikto.ai.agent.telegram.agent_reaction import AgentReaction
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent


def user_message(chat_type: str = 'private') -> Message:
    bot = AsyncMock(spec=Bot)
    chat = Chat(id=42, type=chat_type)
    return Message(message_id=7, date=datetime.now(timezone.utc), chat=chat,
                   from_user=User(id=42, is_bot=False, first_name='User'), text='hi').as_(bot)


DELEGATE = ToolCallPart('delegate_task', {'agent_name': 'child', 'task': 'do it'})
LOOKUP = ToolCallPart('lookup', {})


def scripted_model(*calls: ToolCallPart) -> FunctionModel:
    """Model that makes ``calls`` one per turn, then answers ``final``."""
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        turn = len(messages) // 2
        return ModelResponse(parts=[calls[turn] if turn < len(calls) else TextPart('final')])
    return FunctionModel(respond)


def build(*, parent: str | None, child: str | None, calls: tuple[ToolCallPart, ...] = (DELEGATE,),
          child_calls: tuple[ToolCallPart, ...] = (), reactions: AgentReaction | None = None) -> Agent:
    expert = Agent(model=scripted_model(*child_calls), name='child', description='child expert', metadata={'reaction': child})
    expert.tool_plain(lookup)
    sub_agents = KiberniktoSubAgents(agents=[SubAgent(expert)], agent_folders=None,
                                     shared_capabilities=[reactions or AgentReaction()])
    agent = build_telegram_agent(model=scripted_model(*calls), name='parent', history_storage=None,
                                 persona=False, reaction=parent, capabilities=[sub_agents])
    agent.tool_plain(lookup)
    return agent


def lookup() -> str:
    """Offline stand-in for any ordinary tool."""
    return 'found'


async def run(agent: Agent, message: Message | None = None, **deps: bool) -> str:
    run_deps = TelegramDeps(message=message, **deps)
    result = await agent.run('hi', deps=run_deps)
    await asyncio.gather(*run_deps.extra.get('reaction_tasks', ()))  # Reactions are fire-and-forget.
    return result.output


def emojis(message: Message) -> list[str]:
    calls = message.bot.set_message_reaction.await_args_list
    return [call.kwargs['reaction'][0].emoji for call in calls]


class AgentReactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_chatter_gets_no_reaction(self) -> None:
        message = user_message()
        self.assertEqual(await run(build(parent='👀', child='✍', calls=()), message), 'final')
        message.bot.set_message_reaction.assert_not_awaited()

    async def test_root_reacts_on_its_own_tool_call(self) -> None:
        message = user_message()
        await run(build(parent='👀', child='✍', calls=(LOOKUP, LOOKUP)), message)
        self.assertEqual(emojis(message), ['👀'])
        message.bot.set_message_reaction.assert_awaited_with(
            chat_id=42, message_id=7, reaction=[ReactionTypeEmoji(emoji='👀')])

    async def test_delegation_shows_only_the_delegate_emoji(self) -> None:
        message = user_message()
        self.assertEqual(await run(build(parent='👀', child='✍'), message), 'final')
        self.assertEqual(emojis(message), ['✍'])

    async def test_delegate_tool_calls_rotate_the_working_reaction(self) -> None:
        message = user_message()
        agent = build(parent='👀', child='✍', child_calls=(LOOKUP,) * 5,
                      reactions=AgentReaction(reaction_interval=0))
        await run(agent, message)
        sent = emojis(message)
        self.assertEqual(len(sent), 6)
        self.assertEqual(sent[0], '✍')
        self.assertTrue(set(sent[1:]) <= set(AgentReaction.tool_reactions))
        self.assertTrue(all(a != b for a, b in zip(sent, sent[1:])))  # Every tool call visibly changes it.

    async def test_reactions_are_throttled_per_run(self) -> None:
        message = user_message()
        await run(build(parent='👀', child='✍', child_calls=(LOOKUP,) * 5), message)  # Default interval.
        self.assertEqual(emojis(message), ['✍'])  # One shared window: the tool calls right after the start fall in it.

    async def test_throttle_is_shared_by_every_source(self) -> None:
        message = user_message()
        await run(build(parent='👀', child='✍', calls=(LOOKUP, DELEGATE)), message)
        self.assertEqual(emojis(message), ['👀'])  # The delegate start is throttled by the root's tool reaction.

    async def test_tool_reaction_resumes_after_the_interval(self) -> None:
        message = user_message()
        clock = iter(range(0, 100, 10))
        # Patch the module's `time` name, not time.monotonic itself: the event loop uses the real clock.
        with patch('kibernikto.ai.agent.telegram.agent_reaction.time') as fake_time:
            fake_time.monotonic.side_effect = lambda: next(clock)
            await run(build(parent='👀', child='✍', child_calls=(LOOKUP,) * 3), message)
        self.assertEqual(len(emojis(message)), 4)  # Each call is 10s apart: all pass the 2.5s window.

    async def test_parallel_tool_calls_send_one_reaction(self) -> None:
        message = user_message()
        two = ToolCallPart('lookup', {}, tool_call_id='b')
        expert = Agent(name='child', description='child expert', metadata={'reaction': '✍'},
                       model=FunctionModel(lambda messages, info: ModelResponse(
                           parts=[LOOKUP, two] if len(messages) == 1 else [TextPart('done')])))
        expert.tool_plain(lookup)
        roster = KiberniktoSubAgents(agents=[SubAgent(expert)], agent_folders=None, shared_capabilities=[AgentReaction()])
        parent = build_telegram_agent(model=scripted_model(DELEGATE), name='parent', history_storage=None,
                                      persona=False, reaction='👀', capabilities=[roster])
        await run(parent, message)
        self.assertEqual(len(emojis(message)), 1)  # Start emoji opens the window; both parallel calls fall in it.

    async def test_master_switch_silences_every_agent(self) -> None:
        message = user_message()
        with patch.object(APP_SETTINGS, 'REACTIONS_ENABLED', False):  # Read when the capabilities are built.
            agent = build(parent='👀', child='✍', calls=(LOOKUP, DELEGATE), child_calls=(LOOKUP,))
        self.assertEqual(await run(agent, message), 'final')
        message.bot.set_message_reaction.assert_not_awaited()

    async def test_working_reaction_can_be_disabled(self) -> None:
        message = user_message()
        expert = Agent(model=scripted_model(LOOKUP), name='child', description='child expert', metadata={'reaction': '✍'})
        expert.tool_plain(lookup)
        roster = KiberniktoSubAgents(agents=[SubAgent(expert)], agent_folders=None,
                                     shared_capabilities=[AgentReaction(tool_reactions=())])
        parent = build_telegram_agent(model=scripted_model(DELEGATE), name='parent', history_storage=None,
                                      persona=False, reaction='👀', capabilities=[roster])
        await run(parent, message)
        self.assertEqual(emojis(message), ['✍'])

    async def test_root_tool_then_delegate_last_one_stays(self) -> None:
        message = user_message()
        agent = build(parent='👀', child='✍', calls=(LOOKUP, DELEGATE), reactions=AgentReaction(reaction_interval=0))
        await run(agent, message)
        self.assertEqual(emojis(message), ['👀', '✍'])

    async def test_same_emoji_is_not_resent(self) -> None:
        message = user_message()
        await run(build(parent='👀', child='👀', calls=(LOOKUP, DELEGATE)), message)
        self.assertEqual(emojis(message), ['👀'])

    async def test_agent_without_reaction_sends_nothing(self) -> None:
        message = user_message()
        await run(build(parent=None, child=None, calls=(LOOKUP, DELEGATE)), message)
        message.bot.set_message_reaction.assert_not_awaited()

    async def test_telegram_failure_never_fails_the_run(self) -> None:
        message = user_message()
        message.bot.set_message_reaction.side_effect = TelegramBadRequest(
            method=SetMessageReaction(chat_id=42, message_id=7), message='REACTION_INVALID')
        with self.assertLogs('kibernikto.ai.agent.telegram.agent_reaction', 'WARNING'):
            self.assertEqual(await run(build(parent='👀', child='✍', calls=(LOOKUP, DELEGATE)), message), 'final')

    async def test_no_message_or_peer_envelope_skips_telegram(self) -> None:
        message = user_message()
        await run(build(parent='👀', child='✍', calls=(LOOKUP, DELEGATE)))
        await run(build(parent='👀', child='✍', calls=(LOOKUP, DELEGATE)), message, billable=False)
        message.bot.set_message_reaction.assert_not_awaited()

    async def test_deps_less_run_is_untouched(self) -> None:
        agent = build(parent='👀', child='✍', calls=(LOOKUP, DELEGATE))
        self.assertEqual((await agent.run('hi')).output, 'final')

    async def test_new_experts_react_when_delegated(self) -> None:
        from pydantic import SecretStr
        from pydantic_ai.toolsets import FunctionToolset
        from kibernikto.ai.agent.addons.business.config import BusinessSettings
        from kibernikto.ai.agent.addons.business.agent import build_business_expert
        from kibernikto.ai.agent.addons.travel.kiwi.agent import build_kiwi_expert
        from kibernikto.ai.agent.addons.travel.agent import build_travel_expert
        from kibernikto.ai.agent.addons.travel.tutu.agent import build_tutu_expert
        from kibernikto.ai.agent.addons.vkusvill.config import VkusvillSettings
        from kibernikto.ai.agent.addons.vkusvill.agent import build_vkusvill_expert

        with patch('kibernikto.ai.agent.addons.vkusvill.agent.build_vkusvill_toolset', return_value=FunctionToolset()), \
             patch('kibernikto.ai.agent.harness.delegation.infer_kibernikto_model', return_value=scripted_model()):
            shop = build_vkusvill_expert(VkusvillSettings(_env_file=None, MODEL_NAME='openrouter:test/offline'))
        experts = [
            (build_travel_expert(model=scripted_model(), experts=[]), '👀'),
            (build_tutu_expert(model=scripted_model(), toolset=FunctionToolset()), '🤓'),
            (build_kiwi_expert(model=scripted_model(), toolset=FunctionToolset()), '😎'),
            (build_business_expert(settings=BusinessSettings(_env_file=None, DADATA_TOKEN=SecretStr('fake:fake')),
                                   model=scripted_model(), toolset=FunctionToolset()), '🤝'),
            (shop, '👍'),
        ]
        for expert, expected in experts:
            with self.subTest(agent=expert.name):
                message = user_message()
                delegate = ToolCallPart('delegate_task', {'agent_name': expert.name, 'task': 'test'})
                roster = KiberniktoSubAgents(agents=[expert], agent_folders=None,
                                             shared_capabilities=[AgentReaction()])
                parent = build_telegram_agent(model=scripted_model(delegate), name='parent', history_storage=None,
                                              persona=False, reaction='👀', capabilities=[roster])
                self.assertEqual(await run(parent, message), 'final')
                self.assertEqual(emojis(message), [expected])

    async def test_nested_travel_reactions_through_real_parent(self) -> None:
        from pydantic_ai.capabilities import AbstractCapability
        from pydantic_ai.toolsets import FunctionToolset
        from kibernikto.ai.agent.addons.travel.kiwi.agent import build_kiwi_expert
        from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent
        from kibernikto.ai.agent.addons.travel.config import TRAVEL_SETTINGS
        from kibernikto.ai.agent.addons.travel.agent import build_travel_expert
        from kibernikto.ai.agent.addons.travel.tutu.agent import build_tutu_expert
        from kibernikto.ai.agent.addons.vkusvill.config import VKUSVILL_SETTINGS
        from kibernikto.storage.base import MemoryHistoryStorage
        from kibernikto.storage.models import ConversationInfo

        for name, builder, expected in [('tutu', build_tutu_expert, '🤓'), ('kiwi', build_kiwi_expert, '😎')]:
            with self.subTest(agent=name):
                seen = []
                def child_model(messages, info):
                    seen.append(name)
                    return ModelResponse(parts=[TextPart('found')])
                child = builder(model=FunctionModel(child_model), toolset=FunctionToolset())
                delegate = ToolCallPart('delegate_task', {'agent_name': name, 'task': 'find'})
                def factory(**kwargs):
                    return build_travel_expert(model=scripted_model(delegate), experts=[child], **kwargs)
                with patch.object(TRAVEL_SETTINGS, 'ENABLED', True), \
                     patch('kibernikto.ai.agent.telegram.agent_reaction.time') as clock, \
                     patch('kibernikto.ai.agent.addons.travel.tutu.config.TUTU_SETTINGS.ENABLED', True), \
                     patch.object(VKUSVILL_SETTINGS, 'ENABLED', False), \
                     patch('kibernikto.ai.agent.addons.travel.agent.build_travel_expert', side_effect=factory), \
                     patch('kibernikto.ai.agent.telegram.multi_agent.get_history_storage', return_value=MemoryHistoryStorage()), \
                     patch('kibernikto.ai.agent.telegram.multi_agent.ConversationMemory', return_value=AbstractCapability()), \
                     patch('kibernikto.ai.agent.telegram.multi_agent.CreditTier', return_value=AbstractCapability()):
                    clock.monotonic.side_effect = iter(range(0, 1000, 10)).__next__  # Every reaction outside the window.
                    parent = build_multi_agent()
                    message = user_message()
                    root_call = ToolCallPart('delegate_task', {'agent_name': 'travel', 'task': 'find'})
                    deps = TelegramDeps(message=message, is_personal=True, chat_info=ConversationInfo(credits=3000))
                    with parent.override(model=scripted_model(root_call)):
                        result = await parent.run('test', deps=deps, conversation_id=f'reaction-{name}')
                    self.assertEqual(result.output, 'final')
                    self.assertEqual(seen, [name])
                    self.assertEqual(emojis(message), ['👀', expected])

    async def test_default_experts_carry_their_reactions(self) -> None:
        from pydantic_ai.models.test import TestModel
        result = await image_agent.run('hi', model=TestModel(call_tools=[]))
        self.assertEqual((image_agent.name, result.metadata['reaction']), ('image-agent', '✍'))


def telegram_allowed_emojis() -> set[str]:
    """Reaction emojis Telegram accepts; the list lives in the ReactionTypeEmoji field docstring."""
    import inspect
    import re
    return set(re.findall(r'"([^",.]+)"', inspect.getsource(ReactionTypeEmoji).split('one of', 1)[1]))


class ReactionEmojiAllowedTest(unittest.IsolatedAsyncioTestCase):
    def test_hardcoded_reactions_are_telegram_allowed(self):
        import re
        from pathlib import Path
        allowed = telegram_allowed_emojis()
        self.assertIn('👍', allowed)
        root = Path(__file__).resolve().parent.parent / 'kibernikto'
        used = {m for p in root.rglob('*.py') for m in re.findall(r"""['"]reaction['"]:\s*['"]([^'"]+)['"]""", p.read_text())}
        self.assertTrue(used)
        self.assertEqual(used - allowed, set())

    def test_configured_defaults_are_telegram_allowed(self):
        import inspect
        from kibernikto.ai.agent.core.config import AgentKiberniktoSettings
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
        allowed = telegram_allowed_emojis()
        defaults = {
            'AGENT_KIBERNIKTO_REACTION': AgentKiberniktoSettings.model_fields['REACTION'].default,
            'AgentReaction.steered_reaction': AgentReaction.steered_reaction,
            'TelegramPeerAgent.reaction': inspect.signature(TelegramPeerAgent.__init__).parameters['reaction'].default,
        }
        defaults.update({f'AgentReaction.tool_reactions[{i}]': e for i, e in enumerate(AgentReaction.tool_reactions)})
        for name, emoji in defaults.items():
            with self.subTest(source=name):
                self.assertIn(emoji, allowed)

    async def test_every_built_expert_reaction_is_telegram_allowed(self):
        from pydantic import SecretStr
        from pydantic_ai.models.test import TestModel
        from pydantic_ai.toolsets import FunctionToolset
        from kibernikto.ai.agent.addons.business.agent import build_business_expert
        from kibernikto.ai.agent.addons.business.config import BusinessSettings
        from kibernikto.ai.agent.addons.travel.agent import build_travel_expert
        from kibernikto.ai.agent.addons.travel.kiwi.agent import build_kiwi_expert
        from kibernikto.ai.agent.addons.travel.travala.agent import build_travala_expert
        from kibernikto.ai.agent.addons.travel.tutu.agent import build_tutu_expert
        from kibernikto.ai.agent.addons.vkusvill.agent import build_vkusvill_expert
        from kibernikto.ai.agent.addons.vkusvill.config import VkusvillSettings
        from kibernikto.ai.agent.harness.web import _web_expert

        model, tools = TestModel(call_tools=[]), FunctionToolset()
        with patch('kibernikto.ai.agent.addons.vkusvill.agent.build_vkusvill_toolset', return_value=tools), \
             patch('kibernikto.ai.agent.harness.delegation.infer_kibernikto_model', return_value=model), \
             patch('kibernikto.ai.agent.harness.web.infer_kibernikto_model', return_value=model):
            agents = [
                image_agent,
                _web_expert('openrouter:test/offline'),
                build_travel_expert(model=model, experts=[]).agent,
                build_tutu_expert(model=model, toolset=tools).agent,
                build_kiwi_expert(model=model, toolset=tools).agent,
                build_travala_expert(model=model, toolset=tools).agent,
                build_business_expert(settings=BusinessSettings(_env_file=None, DADATA_TOKEN=SecretStr('fake:fake')),
                                      model=model, toolset=tools).agent,
                build_vkusvill_expert(VkusvillSettings(_env_file=None, MODEL_NAME='openrouter:test/offline')).agent,
            ]
        allowed = telegram_allowed_emojis()
        for agent in agents:
            with self.subTest(agent=agent.name):
                result = await agent.run('hi', model=model, deps=TelegramDeps())
                self.assertIn(result.metadata['reaction'], allowed)
