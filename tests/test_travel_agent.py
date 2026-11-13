"""Travel routing, access control, MCP safety and timezone-aware durations."""
import importlib
import importlib.util
import os
import unittest
from unittest.mock import patch

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import FunctionToolset, ModelResponse, RunContext, RunUsage, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.exceptions import ModelRetry

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent
from kibernikto.ai.agent.vkusvill.config import VKUSVILL_SETTINGS
from kibernikto.ai.agent.vkusvill.expert import CreditGatedSubAgents
from kibernikto.storage.base import MemoryHistoryStorage
from kibernikto.storage.models import ConversationInfo


def travel_module():
    spec = importlib.util.find_spec('kibernikto.ai.agent.travel')
    if spec is None:
        raise AssertionError('travel expert package is missing')
    return importlib.import_module('kibernikto.ai.agent.travel.expert')


class TravelTests(unittest.IsolatedAsyncioTestCase):
    def context(self, credits, personal):
        return RunContext(deps=TelegramDeps(is_personal=personal, chat_info=ConversationInfo(credits=credits)),
                          model=TestModel(), usage=RunUsage(), conversation_id='42')

    async def test_travel_and_tutu_have_configurable_larger_output(self):
        travel = travel_module()
        config = importlib.import_module('kibernikto.ai.agent.travel.config')
        settings = config.TravelSettings(_env_file=None)
        self.assertEqual(settings.MODEL_MAX_TOKENS, 8192)
        coordinator = travel.build_travel_expert(settings=settings, model=TestModel(), experts=[]).agent
        tutu = travel.build_tutu_expert(settings=settings, model=TestModel(), toolset=FunctionToolset()).agent
        self.assertEqual(coordinator.model_settings['max_tokens'], 8192)
        self.assertEqual(tutu.model_settings['max_tokens'], 8192)
        with patch.dict(os.environ, {'AGENT_TRAVEL_TUTU_MODEL_MAX_TOKENS': '32768'}, clear=False):
            configured = config.TravelSettings(_env_file=None)
            tutu = travel.build_tutu_expert(settings=configured, model=TestModel(), toolset=FunctionToolset()).agent
            coordinator = travel.build_travel_expert(settings=configured, model=TestModel(), experts=[]).agent
            self.assertEqual(tutu.model_settings['max_tokens'], 32768)
            self.assertEqual(coordinator.model_settings['max_tokens'], 8192)
        with patch.dict(os.environ, {'AGENT_TRAVEL_MODEL_MAX_TOKENS': '12000'}, clear=False):
            configured = config.TravelSettings(_env_file=None)
            tutu = travel.build_tutu_expert(settings=configured, model=TestModel(), toolset=FunctionToolset()).agent
            coordinator = travel.build_travel_expert(settings=configured, model=TestModel(), experts=[]).agent
            self.assertEqual(tutu.model_settings['max_tokens'], 8192)
            self.assertEqual(coordinator.model_settings['max_tokens'], 12000)

    async def test_model_requests_receive_configured_output_limits(self):
        travel = travel_module()
        from kibernikto.ai.agent.kiwi.expert import build_kiwi_expert
        seen = []
        def model(messages, info):
            seen.append(info.model_settings['max_tokens'])
            return ModelResponse(parts=[TextPart('ok')])
        fn = FunctionModel(model)
        agents = [travel.build_travel_expert(model=fn, experts=[]).agent,
                  travel.build_tutu_expert(model=fn, toolset=FunctionToolset()).agent,
                  build_kiwi_expert(model=fn, toolset=FunctionToolset()).agent]
        for agent in agents:
            await agent.run('hello', deps=TelegramDeps())
        self.assertEqual(seen, [8192, 8192, 8192])

    async def test_tutu_override_reaches_model_without_changing_coordinator(self):
        travel = travel_module()
        config = importlib.import_module('kibernikto.ai.agent.travel.config')
        settings = config.TravelSettings(_env_file=None, TUTU_MODEL_MAX_TOKENS=32768)
        seen = []
        def model(messages, info):
            seen.append(info.model_settings['max_tokens'])
            return ModelResponse(parts=[TextPart('ok')])
        fn = FunctionModel(model)
        coordinator = travel.build_travel_expert(settings=settings, model=fn, experts=[]).agent
        tutu = travel.build_tutu_expert(settings=settings, model=fn, toolset=FunctionToolset()).agent
        await coordinator.run('hello', deps=TelegramDeps())
        await tutu.run('hello', deps=TelegramDeps())
        self.assertEqual(seen, [8192, 32768])

    async def test_tutu_allowlist_excludes_personal_data_and_unknown_tools(self):
        travel = travel_module()
        server = FunctionToolset()
        for name in ('search_avia', 'search_hotels', 'get_offer_details', 'create_checkout_link',
                     'register_checkout_passengers', 'future_write_tool'):
            def tool():
                return 'ok'
            server.add_function(tool, name=name)
        filtered = travel.tutu_toolset(server)
        ctx = self.context(3000, True)
        async with filtered:
            tools = await filtered.get_tools(ctx)
        self.assertEqual(set(tools), {'search_avia', 'search_hotels', 'get_offer_details', 'create_checkout_link'})

        def force_forbidden(messages, info):
            if any(p.part_kind == 'retry-prompt' for m in messages for p in m.parts):
                return ModelResponse(parts=[TextPart('not allowed')])
            return ModelResponse(parts=[ToolCallPart('register_checkout_passengers', {})])

        agent = travel.build_tutu_expert(model=FunctionModel(force_forbidden), toolset=server).agent
        result = await agent.run('register a passport', deps=TelegramDeps())
        self.assertEqual(result.output, 'not allowed')

    async def test_elapsed_time_includes_layover_and_timezone(self):
        travel = travel_module()
        self.assertEqual(travel.elapsed_minutes('2027-01-27T21:15:00+03:00',
                                               '2027-01-28T18:50:00+07:00'), 1055)
        self.assertEqual(travel.elapsed_minutes('2027-01-28T08:10:00+08:00',
                                               '2027-01-28T13:25:00+08:00'), 315)
        with self.assertRaises(ModelRetry):
            travel.elapsed_minutes('2027-01-27T21:15:00', '2027-01-28T18:50:00+07:00')
        with self.assertRaises(ModelRetry):
            travel.elapsed_minutes('2027-01-28T18:50:00+07:00', '2027-01-27T21:15:00+03:00')
        with self.assertRaises(ModelRetry):
            travel.elapsed_minutes('invalid', '2027-01-28T18:50:00+07:00')

    async def test_duration_tool_retries_bad_input_then_returns_real_result(self):
        travel = travel_module()
        def model(messages, info):
            parts = [p for m in messages for p in m.parts]
            if any(isinstance(p, ToolReturnPart) and p.tool_name == 'elapsed_minutes' for p in parts):
                return ModelResponse(parts=[TextPart('duration calculated')])
            if any(p.part_kind == 'retry-prompt' for p in parts):
                args = {'departure': '2027-01-27T21:15:00+03:00', 'arrival': '2027-01-28T18:50:00+07:00'}
            else:
                args = {'departure': '2027-01-27T21:15:00', 'arrival': '2027-01-28T18:50:00+07:00'}
            return ModelResponse(parts=[ToolCallPart('elapsed_minutes', args)])
        agent = travel.build_tutu_expert(model=FunctionModel(model), toolset=FunctionToolset()).agent
        result = await agent.run('calculate total travel time', deps=TelegramDeps())
        results = [p.content for m in result.all_messages() for p in m.parts
                   if isinstance(p, ToolReturnPart) and p.tool_name == 'elapsed_minutes']
        self.assertEqual(results, [1055])

    async def test_tutu_instruction_requires_timezone_calculation_and_honest_freshness(self):
        travel = travel_module()
        text = travel.TUTU_INSTRUCTIONS.lower()
        self.assertIn('elapsed_minutes', text)
        self.assertIn('пересад', text)
        self.assertIn('актуальн', text)
        self.assertIn('цена', text)

    async def test_parent_delegates_through_travel_to_tutu_and_denies_low_credit_and_groups(self):
        travel = travel_module()
        config = importlib.import_module('kibernikto.ai.agent.travel.config')
        seen = []
        server = FunctionToolset()

        @server.tool_plain(name='search_hotels')
        def search_hotels() -> str:
            seen.append('searched')
            return 'hotel-found-from-tutu'

        def child_model(messages, info):
            if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
                return ModelResponse(parts=[TextPart('hotel-found-from-tutu')])
            return ModelResponse(parts=[ToolCallPart('search_hotels', {})])

        child = travel.build_tutu_expert(model=FunctionModel(child_model), toolset=server)

        def middle(messages, info):
            returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
            if returns:
                return ModelResponse(parts=[TextPart(str(returns[-1].content))])
            return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'tutu', 'task': 'find hotel'})])

        expert = travel.build_travel_expert(model=FunctionModel(middle), experts=[child])

        def parent_model(messages, info):
            returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
            if returns:
                return ModelResponse(parts=[TextPart(str(returns[-1].content))])
            if any(p.part_kind == 'retry-prompt' for m in messages for p in m.parts):
                return ModelResponse(parts=[TextPart('expert unavailable')])
            return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'travel', 'task': 'find hotel'})])

        with patch.object(config.TRAVEL_SETTINGS, 'ENABLED', True), \
             patch.object(VKUSVILL_SETTINGS, 'ENABLED', False), \
             patch('kibernikto.ai.agent.travel.expert.build_travel_expert', return_value=expert), \
             patch('kibernikto.ai.agent.telegram.multi_agent.get_history_storage', return_value=MemoryHistoryStorage()), \
             patch('kibernikto.ai.agent.telegram.multi_agent.ConversationMemory', return_value=AbstractCapability()):
            parent = build_multi_agent()
            for credits, personal, expected in [(2001, True, 1), (2000, True, 0), (5000, False, 0)]:
                with self.subTest(credits=credits, personal=personal):
                    seen.clear()
                    deps = TelegramDeps(is_personal=personal, chat_info=ConversationInfo(credits=credits), billable=False)
                    with parent.override(model=FunctionModel(parent_model)):
                        result = await parent.run('find hotel', deps=deps,
                                                  conversation_id=f'travel-{credits}-{personal}')
                    self.assertEqual(len(seen), expected, result.output)
                    if expected:
                        self.assertIn('hotel-found-from-tutu', str(result.output))

    async def test_parent_roster_exposes_travel_not_kiwi_and_reports_credit_status(self):
        travel_module()
        config = importlib.import_module('kibernikto.ai.agent.travel.config')
        from kibernikto.ai.agent.harness.credit_tier import CreditTier
        with patch.object(config.TRAVEL_SETTINGS, 'ENABLED', True), \
             patch.object(VKUSVILL_SETTINGS, 'ENABLED', False):
            parent = build_multi_agent()
            found = []
            parent.root_capability.apply(lambda cap: found.append(cap) if isinstance(cap, CreditGatedSubAgents) else None)
            names = {a.name for cap in found for a in cap.agents}
            self.assertIn('travel', names)
            self.assertNotIn('kiwi', names)
            self.assertNotIn('tutu', names)
            tier = next(cap for cap in parent.root_capability.capabilities if isinstance(cap, CreditTier))
            self.assertIn('travel (>2000 credits, available)', (await tier.check_credits(self.context(2001, True))).lower())
            self.assertIn('travel (>2000 credits, locked)', (await tier.check_credits(self.context(2000, True))).lower())
            self.assertIn('travel (>2000 credits, unavailable in groups)',
                          (await tier.check_credits(self.context(5000, False))).lower())

    async def test_default_travel_roster_includes_both_sources(self):
        travel = travel_module()
        agent = travel.build_travel_expert(model=TestModel()).agent
        from kibernikto.ai.agent.harness.delegation import KiberniktoSubAgents
        rosters = []
        agent.root_capability.apply(lambda c: rosters.append(c) if isinstance(c, KiberniktoSubAgents) else None)
        self.assertEqual({a.name for r in rosters for a in r.agents}, {'kiwi', 'tutu'})

    async def test_defaults_flags_and_shop_are_independent(self):
        travel_module()
        config = importlib.import_module('kibernikto.ai.agent.travel.config')
        defaults = config.TravelSettings(_env_file=None)
        self.assertFalse(defaults.ENABLED)
        self.assertEqual(defaults.MIN_CREDITS, 2000)
        for travel_on in (False, True):
            for shop_on in (False, True):
                with self.subTest(travel=travel_on, shop=shop_on), \
                     patch.object(config.TRAVEL_SETTINGS, 'ENABLED', travel_on), \
                     patch.object(VKUSVILL_SETTINGS, 'ENABLED', shop_on):
                    parent = build_multi_agent()
                    rosters = []
                    parent.root_capability.apply(
                        lambda c: rosters.append(c) if isinstance(c, CreditGatedSubAgents) else None)
                    names = {a.name for roster in rosters for a in roster.agents}
                    self.assertEqual('travel' in names, travel_on)
                    self.assertEqual('vkusvill' in names, shop_on)
                    self.assertNotIn('kiwi', names)

    async def test_travel_and_shop_thresholds_are_independent(self):
        travel_module()
        config = importlib.import_module('kibernikto.ai.agent.travel.config')
        with patch.object(config.TRAVEL_SETTINGS, 'ENABLED', True), \
             patch.object(config.TRAVEL_SETTINGS, 'MIN_CREDITS', 2000), \
             patch.object(VKUSVILL_SETTINGS, 'ENABLED', True), \
             patch.object(VKUSVILL_SETTINGS, 'MIN_CREDITS', 2500):
            parent = build_multi_agent()
            rosters = []
            parent.root_capability.apply(
                lambda c: rosters.append(c) if isinstance(c, CreditGatedSubAgents) else None)
            for credits, personal, expected in [(2000, True, set()), (2001, True, {'travel'}),
                                                (2500, True, {'travel'}), (2501, True, {'travel', 'vkusvill'}),
                                                (9000, False, set())]:
                with self.subTest(credits=credits, personal=personal):
                    run = await rosters[0].for_run(self.context(credits, personal))
                    self.assertEqual({a.name for a in run.agents} & {'travel', 'vkusvill'}, expected)

    async def test_zero_credit_threshold_remains_private(self):
        travel_module()
        config = importlib.import_module('kibernikto.ai.agent.travel.config')
        from kibernikto.ai.agent.harness.credit_tier import CreditTier
        with patch.object(config.TRAVEL_SETTINGS, 'ENABLED', True), \
             patch.object(config.TRAVEL_SETTINGS, 'MIN_CREDITS', 0), \
             patch.object(VKUSVILL_SETTINGS, 'ENABLED', False):
            parent = build_multi_agent()
            tier = next(c for c in parent.root_capability.capabilities if isinstance(c, CreditTier))
            self.assertIn('travel (no minimum credits, available)',
                          (await tier.check_credits(self.context(0, True))).lower())
            self.assertIn('travel (no minimum credits, unavailable in groups)',
                          (await tier.check_credits(self.context(3000, False))).lower())

    async def test_expert_failure_is_contained_for_travel_agent(self):
        travel = travel_module()
        def fail():
            raise RuntimeError('provider unavailable')
        bad = FunctionToolset()
        bad.add_function(fail, name='search_hotels')
        child = travel.build_tutu_expert(model=TestModel(), toolset=bad)
        def middle(messages, info):
            if any(p.part_kind == 'retry-prompt' for m in messages for p in m.parts):
                return ModelResponse(parts=[TextPart('provider unavailable')])
            return ModelResponse(parts=[ToolCallPart('delegate_task', {'agent_name': 'tutu', 'task': 'find hotel'})])
        expert = travel.build_travel_expert(model=FunctionModel(middle), experts=[child])
        with self.assertLogs(level='WARNING'):
            result = await expert.agent.run('find hotel', deps=TelegramDeps())
        self.assertIn('unavailable', result.output)
