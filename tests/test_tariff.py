import unittest
from unittest.mock import patch

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.harness.credit_tier import format_credit_status
from kibernikto.ai.agent.harness.tariff import Tariff


class TariffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rich = AGENT_KIBERNIKTO_SETTINGS.RICH_CREDITS

    def test_locked_private_chat_names_missing_credits(self) -> None:
        tariff = Tariff(260, is_personal=True, gated=('herenow',))
        self.assertFalse(tariff.experts_open)
        self.assertIn(f'{self.rich - 260} more credits', tariff.experts_line())
        self.assertIn('herenow', tariff.balance_text())
        self.assertIn('🔒', tariff.balance_text())

    def test_group_is_locked_even_when_rich(self) -> None:
        tariff = Tariff(self.rich + 1000, is_personal=False, gated=('herenow', 'travel'))
        self.assertFalse(tariff.experts_open)
        self.assertIn('private chat', tariff.experts_line())

    def test_rich_private_chat_is_open(self) -> None:
        tariff = Tariff(self.rich, is_personal=True, gated=('herenow',))
        self.assertTrue(tariff.experts_open)
        self.assertIsNone(tariff.experts_line())
        self.assertNotIn('Experts', tariff.balance_text())

    def test_no_enabled_experts_keeps_plain_balance(self) -> None:
        tariff = Tariff(10, gated=())
        self.assertIsNone(tariff.experts_line())
        self.assertNotIn('Experts', tariff.balance_text())

    def test_credit_status_carries_experts_line(self) -> None:
        with patch('kibernikto.ai.agent.harness.tariff.enabled_gated_experts', return_value=('herenow',)):
            text = format_credit_status(260, is_personal=True)
        self.assertIn('experts: locked: herenow', text)
