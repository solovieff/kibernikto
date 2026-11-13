"""Offline AgentReaction regressions: parent and delegate emojis on the user's message, failures stay cosmetic."""

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

from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents
from kibernikto.ai.agent.harness.image_agent import image_agent
from kibernikto.ai.agent.telegram.agent_reaction import AgentReaction
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent


def user_message() -> Message:
    bot = AsyncMock(spec=Bot)
    chat = Chat(id=42, type='private')
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
          child_calls: tuple[ToolCallPart, ...] = ()) -> Agent:
    expert = Agent(model=scripted_model(*child_calls), name='child', description='child expert', metadata={'reaction': child})
    expert.tool_plain(lookup)
    sub_agents = KiberniktoSubAgents(agents=[SubAgent(expert)], agent_folders=None,
                                     shared_capabilities=[AgentReaction()])
    agent = build_telegram_agent(model=scripted_model(*calls), name='parent', history_storage=None,
                                 persona=False, reaction=parent, capabilities=[sub_agents])
    agent.tool_plain(lookup)
    return agent


def lookup() -> str:
    """Offline stand-in for any ordinary tool."""
    return 'found'


async def run(agent: Agent, message: Message | None = None, **deps: bool) -> str:
    result = await agent.run('hi', deps=TelegramDeps(message=message, **deps))
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
        self.assertEqual(await run(build(parent='👀', child='✍', child_calls=(LOOKUP,)), message), 'final')
        self.assertEqual(emojis(message), ['✍'])

    async def test_root_tool_then_delegate_last_one_stays(self) -> None:
        message = user_message()
        await run(build(parent='👀', child='✍', calls=(LOOKUP, DELEGATE)), message)
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
                     patch.object(VKUSVILL_SETTINGS, 'ENABLED', False), \
                     patch('kibernikto.ai.agent.addons.travel.agent.build_travel_expert', side_effect=factory), \
                     patch('kibernikto.ai.agent.telegram.multi_agent.get_history_storage', return_value=MemoryHistoryStorage()), \
                     patch('kibernikto.ai.agent.telegram.multi_agent.ConversationMemory', return_value=AbstractCapability()), \
                     patch('kibernikto.ai.agent.telegram.multi_agent.CreditTier', return_value=AbstractCapability()):
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
