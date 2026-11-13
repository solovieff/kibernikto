"""Offline CreditTier regressions: tier selection, chat_data loads per message, charging, peer bypass."""

import os
import unittest
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import ModelMessage, ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai_harness.exa import ExaSearch
from pydantic_ai_harness.subagents import SubAgent, SubAgents

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.core.errors import InsufficientCreditsError
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent
from kibernikto.ai.agent.harness.credit_tier import CreditTier
from kibernikto.ai.agent.harness.delegation import DELEGATION_GUIDE
from kibernikto.ai.agent.harness.web import WEB_EXPERT_DESCRIPTION, WEB_EXPERT_INSTRUCTIONS, WEB_EXPERT_NAME, WEB_SEARCH_GUIDANCE
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent
from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent
from kibernikto.storage.base import MemoryHistoryStorage
from kibernikto.storage.models import ConversationInfo
from kibernikto.telegram.bridge import TelegramBridge
from kibernikto.utils.time_utils import get_user_date

POOR, MEDIUM, RICH = 'test:poor', 'test:medium', 'test:rich'
POOR_PREFIXED = 'openrouter:test/poor'


class CountingChatData:
    """In-memory ChatDataStore that counts loads."""

    def __init__(self) -> None:
        self.rows: dict[str, ConversationInfo] = {}
        self.loads = 0

    async def load(self, conversation_id: str) -> ConversationInfo:
        self.loads += 1
        return self.rows.get(str(conversation_id), ConversationInfo()).model_copy(deep=True)

    async def save(self, conversation_id: str, info: ConversationInfo) -> None:
        self.rows[str(conversation_id)] = info.model_copy(deep=True)


def named_model(name: str, *, tool_step: bool = False) -> FunctionModel:
    """Model that answers with its own name; optionally calls a tool first to force a second step."""
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if tool_step and len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart('ping', {})])
        return ModelResponse(parts=[TextPart(name)])
    return FunctionModel(respond, model_name=name)


class CreditTierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.chat_data = CountingChatData()
        patcher = patch('kibernikto.ai.agent.harness.credit_tier.chat_data', self.chat_data)
        patcher.start()
        self.addCleanup(patcher.stop)
        settings = patch.multiple(AGENT_KIBERNIKTO_SETTINGS, POOR_CREDITS=30, RICH_CREDITS=500,
                                  POOR_MODEL=POOR_PREFIXED, MEDIUM_MODEL=MEDIUM, RICH_MODEL=RICH, ALLOW_ZERO_CREDITS=True)
        settings.start()
        self.addCleanup(settings.stop)
        self.tier = CreditTier(models={name: named_model(name, tool_step=True) for name in (POOR, POOR_PREFIXED, MEDIUM, RICH)})
        self.history = MemoryHistoryStorage()
        self.agent = build_telegram_agent(model=named_model('fallback'), name='credit-test',
                                   history_storage=self.history, capabilities=[self.tier])

        @self.agent.tool_plain
        def ping() -> str:
            return 'pong'

    async def set_credits(self, conversation_id: int | str, credits: int) -> None:
        await self.chat_data.save(str(conversation_id), ConversationInfo(credits=credits))
        self.chat_data.loads = 0

    async def test_tier_selects_model_and_charges_once(self) -> None:
        for credits, expected in ((5, POOR_PREFIXED), (100, MEDIUM), (900, RICH)):
            with self.subTest(credits=credits):
                await self.set_credits('7', credits)
                result = await self.agent.run('hi', conversation_id='7', deps=TelegramDeps())
                self.assertEqual(result.output, expected)
                self.assertEqual(self.chat_data.rows['7'].credits, credits - 1)
                self.assertEqual(self.chat_data.loads, 2)  # One select across both steps + one charge.

    async def test_build_deps_snapshot_skips_the_select_load(self) -> None:
        await self.set_credits('7', 900)
        result = await self.agent.run('hi', conversation_id='7', deps=TelegramDeps(chat_info=self.chat_data.rows['7']))
        self.assertEqual(result.output, RICH)
        self.assertEqual(self.chat_data.loads, 1)  # Charge only: tier came from the snapshot.

    async def test_exhausted_balance_continues_on_poor_model_by_default(self) -> None:
        for credits in (0, -5):
            await self.set_credits('7', credits)
            result = await self.agent.run('hi', conversation_id='7', deps=TelegramDeps())
            self.assertEqual(result.output, POOR_PREFIXED)
            self.assertEqual(self.chat_data.rows['7'].credits, 0)

    async def test_strict_policy_blocks_exhausted_balance_even_with_model_override(self) -> None:
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'ALLOW_ZERO_CREDITS', False):
            for credits in (0, -5):
                await self.set_credits('7', credits)
                with self.assertRaises(InsufficientCreditsError):
                    await self.agent.run('hi', conversation_id='7', deps=TelegramDeps())
                model = TestModel(custom_output_text='must not run')
                with self.agent.override(model=model), self.assertRaises(InsufficientCreditsError):
                    await self.agent.run('hi', conversation_id='7', deps=TelegramDeps())
                self.assertIsNone(model.last_model_request_parameters)
                self.assertEqual(self.chat_data.rows['7'].credits, credits)
                self.assertFalse(await self.history.get_conversation('7'))

    async def test_strict_policy_allows_last_credit_then_top_up_restores_access(self) -> None:
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'ALLOW_ZERO_CREDITS', False):
            await self.set_credits('7', 1)
            result = await self.agent.run('hi', conversation_id='7', deps=TelegramDeps())
            self.assertEqual(result.output, POOR_PREFIXED)
            self.assertEqual(self.chat_data.rows['7'].credits, 0)
            with self.assertRaises(InsufficientCreditsError):
                await self.agent.run('hi', conversation_id='7', deps=TelegramDeps())
            await self.set_credits('7', 100)
            result = await self.agent.run('hi', conversation_id='7', deps=TelegramDeps())
            self.assertEqual(result.output, MEDIUM)
            self.assertEqual(self.chat_data.rows['7'].credits, 99)

    async def test_strict_policy_does_not_block_non_billable_peers(self) -> None:
        await self.set_credits('7', 0)
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'ALLOW_ZERO_CREDITS', False):
            result = await self.agent.run('hi', conversation_id='7', deps=TelegramDeps(billable=False))
        self.assertEqual(result.output, 'fallback')
        self.assertEqual(self.chat_data.loads, 0)

    async def test_strict_policy_uses_deps_snapshot(self) -> None:
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'ALLOW_ZERO_CREDITS', False):
            with self.assertRaises(InsufficientCreditsError):
                await self.agent.run('hi', conversation_id='7', deps=TelegramDeps(chat_info=ConversationInfo(credits=0)))
        self.assertEqual(self.chat_data.loads, 0)

    async def test_charge_rereads_so_mid_run_top_up_survives(self) -> None:
        await self.set_credits('7', 100)
        stale = self.chat_data.rows['7'].model_copy(deep=True)
        await self.set_credits('7', 600)  # Top-up lands after build_deps took its snapshot.
        await self.agent.run('hi', conversation_id='7', deps=TelegramDeps(chat_info=stale))
        self.assertEqual(self.chat_data.rows['7'].credits, 599)

    async def test_build_deps_reads_chat_data_once_writes_nothing_and_hides_credits(self) -> None:
        from aiogram.types import Message
        message = Message.model_validate({'message_id': 1, 'date': 0, 'text': 'hi',
                                          'chat': {'id': 7, 'type': 'private', 'first_name': 'A'},
                                          'from': {'id': 7, 'is_bot': False, 'first_name': 'A'}})
        await self.set_credits('7', 100)
        saved = dict(self.chat_data.rows)
        with patch('kibernikto.telegram.bridge.chat_data', self.chat_data), \
                patch('kibernikto.telegram.bridge.get_chat_context',
                      AsyncMock(return_value='chat_type: private | full_name: A')):
            deps = await TelegramBridge(self.agent).build_deps(message)
        self.assertEqual(self.chat_data.loads, 1)
        self.assertEqual(self.chat_data.rows, saved)
        self.assertEqual(deps.chat_info.credits, 100)
        self.assertIn('full_name: A', deps.conversation_context)
        self.assertNotIn('credits', deps.conversation_context)

    async def test_instructions_carry_todays_date(self) -> None:
        from pydantic_ai import capture_run_messages
        with capture_run_messages() as messages:
            await self.agent.run('hi', deps=TelegramDeps(billable=False, timezone='Asia/Tokyo'))
        instructions = messages[0].instructions
        self.assertIn(f"Current date: {get_user_date('Asia/Tokyo')}.", instructions)
        self.assertIn('(Asia/Tokyo)', instructions)

    async def test_works_on_a_plain_kibernikto_agent_without_telegram(self) -> None:
        agent = build_kibernikto_agent(model=named_model('fallback'), name='credit-core', history_storage=None,
                                deps_type=KiberniktoDeps, capabilities=[self.tier])
        await self.set_credits('7', 900)
        result = await agent.run('hi', conversation_id='7', deps=KiberniktoDeps())
        self.assertEqual(result.output, RICH)
        self.assertEqual(self.chat_data.rows['7'].credits, 899)
        anonymous = await agent.run('hi', deps=KiberniktoDeps())
        self.assertEqual(anonymous.output, 'fallback')  # No conversation_id: nothing to tier or bill.

    async def test_orchestrator_parent_is_credit_tiered(self) -> None:
        capabilities = build_multi_agent().root_capability.capabilities
        self.assertEqual(len([c for c in capabilities if isinstance(c, CreditTier)]), 1)

    async def test_web_capability_is_exa_with_key_else_researcher(self) -> None:
        with patch.dict(os.environ, {'EXA_API_KEY': 'test-not-a-real-key'}):
            exa = [c for c in build_multi_agent().root_capability.capabilities if isinstance(c, ExaSearch)]
            self.assertEqual(len(exa), 1)
            self.assertTrue(exa[0].native)
            self.assertFalse(exa[0].include_deep_search)
            self.assertEqual(exa[0].guidance, WEB_SEARCH_GUIDANCE)
        with patch.dict(os.environ):
            os.environ.pop('EXA_API_KEY', None)
            names = {type(c).__name__ for c in build_multi_agent().root_capability.capabilities}
            # Researcher is a CombinedCapability: the agent flattens it into its parts.
            self.assertLessEqual({'WebSearch', 'WebFetch', 'ToolOutputLimits'}, names)
            self.assertNotIn('ExaSearch', names)

    async def test_web_model_name_is_a_toolless_personaless_delegate_on_that_model(self) -> None:
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'WEB_MODEL_NAME', 'openrouter:test/web'), \
                patch.object(AGENT_KIBERNIKTO_SETTINGS, 'WHO_AM_I', 'PERSONA-MARK'), \
                patch.dict(os.environ, {'EXA_API_KEY': 'test-not-a-real-key'}):
            capabilities = build_multi_agent().root_capability.capabilities
        names = {type(c).__name__ for c in capabilities}
        self.assertFalse(names & {'ExaSearch', 'WebSearch', 'WebFetch'}, names)
        sub_agents = next(c for c in capabilities if isinstance(c, SubAgents))
        web = next(s.agent for s in sub_agents.agents if s.agent.name == WEB_EXPERT_NAME)
        self.assertEqual(web.model.model_name, 'test/web')
        # The search-native model does the searching: the delegate carries no web tools.
        web_names = {type(c).__name__ for c in web.root_capability.capabilities}
        self.assertFalse(web_names & {'ExaSearch', 'WebSearch', 'WebFetch'}, web_names)
        seen: list[str] = []
        def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen.append(info.instructions or '')
            return ModelResponse(parts=[TextPart('ok')])
        with web.override(model=FunctionModel(capture)):
            await web.run('USD rate?', deps=TelegramDeps())
        self.assertTrue(seen[0].startswith(WEB_EXPERT_INSTRUCTIONS), seen[0])
        self.assertNotIn('PERSONA-MARK', seen[0])
        self.assertIn('Current date:', seen[0])

    async def test_roster_uses_our_delegation_guide(self) -> None:
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'WEB_MODEL_NAME', 'openrouter:test/web'):
            capabilities = build_multi_agent().root_capability.capabilities
        roster = next(c for c in capabilities if isinstance(c, SubAgents)).get_instructions()
        self.assertTrue(roster.startswith(DELEGATION_GUIDE), roster)
        self.assertIn(f'- {WEB_EXPERT_NAME}: {WEB_EXPERT_DESCRIPTION}', roster)
        self.assertIn('- image-agent: ', roster)
        self.assertNotIn('delegate self-contained', roster)

    async def test_non_billable_peer_run_uses_fallback_and_is_free(self) -> None:
        await self.set_credits('7', 100)
        result = await self.agent.run('hi', conversation_id='7', deps=TelegramDeps(billable=False))
        self.assertEqual(result.output, 'fallback')
        self.assertEqual(self.chat_data.rows['7'].credits, 100)
        self.assertEqual(self.chat_data.loads, 0)

    async def test_explicit_override_wins(self) -> None:
        await self.set_credits('7', 100)
        with self.agent.override(model=TestModel(custom_output_text='override')):
            result = await self.agent.run('hi', conversation_id='7', deps=TelegramDeps())
        self.assertEqual(result.output, 'override')
        self.assertEqual(self.chat_data.rows['7'].credits, 99)  # Charging is independent of the model.

    async def test_failed_run_is_not_charged(self) -> None:
        await self.set_credits('7', 100)
        def boom(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise RuntimeError('provider down')
        self.tier.models[MEDIUM] = FunctionModel(boom)
        with self.assertRaises(RuntimeError):
            await self.agent.run('hi', conversation_id='7', deps=TelegramDeps())
        self.assertEqual(self.chat_data.rows['7'].credits, 100)

    def _delegating_agent(self, calls: int, *, child_fails: bool = False):
        def child_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if child_fails:
                raise RuntimeError('child down')
            return ModelResponse(parts=[TextPart('child-done')])

        child = build_kibernikto_agent(model=FunctionModel(child_model), name='child', history_storage=None)
        child.description = 'test child'

        def parent_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            done = sum(isinstance(p, ToolReturnPart | RetryPromptPart) for m in messages for p in getattr(m, 'parts', ()))
            if done < calls:
                return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'child', 'task': 'go'})])
            return ModelResponse(parts=[TextPart('parent-done')])

        roster = SubAgents(agents=[SubAgent(child)], agent_folders=None, contain_errors=True)
        return build_telegram_agent(model=FunctionModel(parent_model), name='delegating', history_storage=None,
                                    capabilities=[CreditTier(models={MEDIUM: FunctionModel(parent_model)}), roster])

    async def test_each_successful_delegation_is_charged_on_top_of_the_run(self) -> None:
        agent = self._delegating_agent(calls=2)
        for effort, expected in ((2, 100 - 1 - 2 * 2), (0, 100 - 1)):
            with self.subTest(subagent_effort=effort), patch.object(AGENT_KIBERNIKTO_SETTINGS, 'SUBAGENT_EFFORT', effort):
                await self.set_credits('7', 100)
                result = await agent.run('hi', conversation_id='7', deps=TelegramDeps())
                self.assertEqual(result.output, 'parent-done')
                self.assertEqual(self.chat_data.rows['7'].credits, expected)

    async def test_failed_delegation_and_non_billable_runs_are_not_charged_extra(self) -> None:
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'SUBAGENT_EFFORT', 3):
            await self.set_credits('7', 100)
            await self._delegating_agent(calls=1, child_fails=True).run('hi', conversation_id='7', deps=TelegramDeps())
            self.assertEqual(self.chat_data.rows['7'].credits, 99)
            await self._delegating_agent(calls=1).run('hi', conversation_id='7', deps=TelegramDeps(billable=False))
            self.assertEqual(self.chat_data.rows['7'].credits, 99)

    async def test_delegation_charge_does_not_leak_between_runs(self) -> None:
        agent = self._delegating_agent(calls=1)
        with patch.object(AGENT_KIBERNIKTO_SETTINGS, 'SUBAGENT_EFFORT', 2):
            await self.set_credits('7', 100)
            await agent.run('hi', conversation_id='7', deps=TelegramDeps())
            await agent.run('hi', conversation_id='7', deps=TelegramDeps())
        self.assertEqual(self.chat_data.rows['7'].credits, 100 - 2 * (1 + 2))

    async def test_check_credits_tool_returns_balance_tier_and_reuses_run_snapshot(self) -> None:
        observed_tool_returns: list[str] = []

        def call_check_credits(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(parts=[ToolCallPart('check_credits', {})])
            for message in messages:
                for part in getattr(message, 'parts', ()):
                    if isinstance(part, ToolReturnPart) and part.tool_name == 'check_credits':
                        observed_tool_returns.append(str(part.content))
            return ModelResponse(parts=[TextPart('checked')])

        self.tier.models[MEDIUM] = FunctionModel(call_check_credits)
        await self.set_credits('7', 120)
        result = await self.agent.run('how many credits do I have?', conversation_id='7', deps=TelegramDeps())
        self.assertEqual(result.output, 'checked')
        self.assertEqual(len(observed_tool_returns), 1)
        self.assertIn('credits: 120', observed_tool_returns[0])
        self.assertIn('tier: medium', observed_tool_returns[0])
        self.assertIn('/balance', observed_tool_returns[0])
        self.assertIn('/pay [stars]', observed_tool_returns[0])
        self.assertNotIn('admin_commands', observed_tool_returns[0])
        self.assertEqual(self.chat_data.loads, 2)  # Initial load shared by _select + check_credits, plus after_run charge.

    async def test_check_credits_tool_includes_admin_grant_commands_for_master_user(self) -> None:
        from kibernikto.telegram.config import TELEGRAM_SETTINGS

        observed_tool_returns: list[str] = []

        def call_check_credits(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(parts=[ToolCallPart('check_credits', {})])
            for message in messages:
                for part in getattr(message, 'parts', ()):
                    if isinstance(part, ToolReturnPart) and part.tool_name == 'check_credits':
                        observed_tool_returns.append(str(part.content))
            return ModelResponse(parts=[TextPart('admin-checked')])

        self.tier.models[MEDIUM] = FunctionModel(call_check_credits)
        await self.set_credits('199740245', 120)
        with patch.multiple(TELEGRAM_SETTINGS, MASTER_ID=199740245, ADMIN_COMMANDS_ALLOWED=True):
            deps = TelegramDeps(user_id=199740245)
        self.assertTrue(deps.is_admin)
        result = await self.agent.run('how to grant credits?', conversation_id='199740245', deps=deps)
        self.assertEqual(result.output, 'admin-checked')
        self.assertEqual(len(observed_tool_returns), 1)
        self.assertIn('admin_commands (caller is admin)', observed_tool_returns[0])
        self.assertIn('/pay <±credits> 199740245', observed_tool_returns[0])
        self.assertIn('/pay <±credits> <tg_id>', observed_tool_returns[0])
        self.assertIn('/balance <tg_id>', observed_tool_returns[0])

    async def test_check_credits_tool_reports_untracked_on_non_billable_run(self) -> None:
        observed_tool_returns: list[str] = []

        def call_check_credits(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(parts=[ToolCallPart('check_credits', {})])
            for message in messages:
                for part in getattr(message, 'parts', ()):
                    if isinstance(part, ToolReturnPart) and part.tool_name == 'check_credits':
                        observed_tool_returns.append(str(part.content))
            return ModelResponse(parts=[TextPart('untracked')])

        with self.agent.override(model=FunctionModel(call_check_credits)):
            result = await self.agent.run('credits?', conversation_id='7', deps=TelegramDeps(billable=False))
        self.assertEqual(result.output, 'untracked')
        self.assertEqual(observed_tool_returns, ['credits: untracked (non-billable run)'])
        self.assertEqual(self.chat_data.loads, 0)


if __name__ == '__main__':
    unittest.main()
