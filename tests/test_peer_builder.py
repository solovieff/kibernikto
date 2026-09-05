"""Public builder compatibility; construction must not contact Telegram."""
import unittest
from unittest.mock import patch

# Reuse the offline import environment, never the production env file.
from tests import test_telegram_peer
from pydantic_ai.models.test import TestModel
from pydantic_ai_harness.subagents import SubAgents
import os
# Legacy expert singletons construct providers on import, but make no requests.
os.environ['VSEGPT_API_KEY'] = 'offline-provider-placeholder'
from kibernikto.ai.agent.extended import orchestrators
from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent


class PeerBuilderTests(unittest.TestCase):
    def test_old_builder_is_unchanged_and_peers_are_opt_in(self):
        original = list(orchestrators._EXPERT_AGENTS)
        peer = TelegramPeerAgent(peer=200, name='remote', description='Remote expert')
        with patch.object(orchestrators, 'infer_kibernikto_model', return_value=TestModel()), \
             patch.object(orchestrators, 'SubAgents', wraps=SubAgents) as capability:
            old = orchestrators.build_subagents_agent()
            old_members = capability.call_args.kwargs['agents']
            self.assertEqual([s.agent for s in old_members], original)
            self.assertTrue(callable(getattr(orchestrators, 'build_subagents_agent_with_tg_peers', None)),
                            'Public Telegram peer builder is missing')
            new = orchestrators.build_subagents_agent_with_tg_peers([peer])
            options = capability.call_args.kwargs
            self.assertEqual([s.agent for s in options['agents']], [*original, peer])
            self.assertIsNone(options['agents'][-1].timeout_seconds)
            self.assertTrue(options['contain_errors'])
            self.assertIsInstance(new, type(old))
            self.assertEqual(orchestrators._EXPERT_AGENTS, original)
            orchestrators.build_subagents_agent()
            self.assertEqual([s.agent for s in capability.call_args.kwargs['agents']], original)

    def test_empty_peers_keeps_local_experts(self):
        self.assertTrue(hasattr(orchestrators, 'build_subagents_agent_with_tg_peers'))
        with patch.object(orchestrators, 'infer_kibernikto_model', return_value=TestModel()), \
             patch.object(orchestrators, 'SubAgents', wraps=SubAgents) as capability:
            orchestrators.build_subagents_agent_with_tg_peers([])
            self.assertEqual([s.agent for s in capability.call_args.kwargs['agents']], orchestrators._EXPERT_AGENTS)
