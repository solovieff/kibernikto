"""Offline AgentReaction regressions: parent and delegate emojis on the user's message, failures stay cosmetic."""

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
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent


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
          child_calls: tuple[ToolCallPart, ...] = ()) -> TelegramAgent:
    expert = Agent(model=scripted_model(*child_calls), name='child', description='child expert')
    expert.reaction = child
    expert.tool_plain(lookup)
    sub_agents = KiberniktoSubAgents(agents=[SubAgent(expert)], agent_folders=None,
                                     shared_capabilities=[AgentReaction()])
    agent = TelegramAgent(model=scripted_model(*calls), name='parent', history_storage=None,
                          persona=False, reaction=parent, capabilities=[sub_agents])
    agent.tool_plain(lookup)
    return agent


def lookup() -> str:
    """Offline stand-in for any ordinary tool."""
    return 'found'


async def run(agent: TelegramAgent, message: Message | None = None, **deps: bool) -> str:
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

    def test_default_experts_carry_their_reactions(self) -> None:
        self.assertEqual((image_agent.name, image_agent.reaction), ('image-agent', '✍'))
