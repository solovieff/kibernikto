"""Offline regressions: bot menu is published from the same COMMANDS that /help renders."""

import unittest
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SetMyCommands

from kibernikto.telegram.handlers.commands import COMMANDS, help_text, set_bot_commands


class BotCommandsTests(unittest.IsolatedAsyncioTestCase):
    async def test_menu_publishes_commands(self) -> None:
        bot = AsyncMock(spec=Bot)
        await set_bot_commands(bot)
        bot.set_my_commands.assert_awaited_once_with(list(COMMANDS))

    async def test_menu_failure_is_only_logged(self) -> None:
        bot = AsyncMock(spec=Bot)
        bot.set_my_commands.side_effect = TelegramNetworkError(method=SetMyCommands(commands=[]), message='down')
        with self.assertLogs('kibernikto.telegram.handlers.commands', 'WARNING'):
            await set_bot_commands(bot)

    def test_help_lists_every_menu_command_html_safe(self) -> None:
        text = help_text()
        for command in COMMANDS:
            self.assertIn(f'/{command.command} - ', text)
        self.assertIn('&lt;tg_id&gt;', text)
        self.assertNotIn('<', text)
