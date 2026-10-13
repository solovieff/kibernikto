"""Offline /reset regressions: permissions, confirmation flow, wipe scope (history + notes, never credits)."""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, User
from pydantic_ai import ModelRequest, UserPromptPart
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness.memory import FileStore, InMemoryStore, SqliteMemoryStore

# The agent package must load first: storage.base and ai.agent import each other.
from kibernikto.telegram.handlers import reset
from kibernikto.telegram.handlers.reset import CANCEL, CONFIRM, cmd_reset, handle_reset_choice
from kibernikto.storage.base import MemoryHistoryStorage
from kibernikto.storage.chat_wipe import wipe_chat, wipe_chat_memory
from kibernikto.telegram.config import TELEGRAM_SETTINGS

NOW = datetime.now(timezone.utc)
ADMIN = User(id=1, is_bot=False, first_name='admin')
USER = User(id=200, is_bot=False, first_name='user')


async def seed(store, *paths: str) -> None:
    for path in paths:
        await store.write(path, 'fact\n', expected_version=None)


class WipeTests(unittest.IsolatedAsyncioTestCase):
    async def check_scope(self, store) -> None:
        await seed(store, '5/bot/MEMORY.md', '5/bot/topic.md', '55/bot/MEMORY.md', '5/other/MEMORY.md', '-7/bot/MEMORY.md')
        self.assertEqual(await wipe_chat_memory(5, 'bot', store), 2)
        left = await store.list_paths('', limit=50)
        self.assertEqual(sorted(left), ['-7/bot/MEMORY.md', '5/other/MEMORY.md', '55/bot/MEMORY.md'])
        self.assertEqual(await wipe_chat_memory(-7, 'bot', store), 1)
        self.assertEqual(await wipe_chat_memory(5, 'bot', store), 0)

    async def test_wipe_is_scoped_to_one_chat_and_agent_in_memory(self) -> None:
        await self.check_scope(InMemoryStore())

    async def test_wipe_is_scoped_on_file_and_sqlite_backends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, 'memory')
            root.mkdir()
            await self.check_scope(FileStore('.', workspace=LocalWorkspaceBackend(root)))
            await self.check_scope(SqliteMemoryStore(database=str(Path(directory, 'memory.db'))))

    async def test_wipe_chat_clears_history_for_that_chat_only(self) -> None:
        history, store = MemoryHistoryStorage(), InMemoryStore()
        request = [ModelRequest(parts=[UserPromptPart('hi')])]
        await history.add_messages(5, request)
        await history.add_messages(6, request)
        await seed(store, '5/bot/MEMORY.md')
        self.assertEqual(await wipe_chat(5, history=history, agent_name='bot', memory=store), 1)
        self.assertEqual(await history.get_full_conversation(5), [])
        self.assertEqual(len(await history.get_full_conversation(6)), 1)

    async def test_wipe_chat_without_history_still_clears_notes(self) -> None:
        store = InMemoryStore()
        await seed(store, '5/bot/MEMORY.md')
        self.assertEqual(await wipe_chat(5, history=None, agent_name='bot', memory=store), 1)


class ResetHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = Bot('100:offline-test-token')
        self.bot.session.make_request = AsyncMock(return_value=True)
        self.addAsyncCleanup(self.bot.session.close)
        self.wipe = AsyncMock(return_value=2)
        for target, value in (('kibernikto.telegram.handlers.reset.wipe_chat', self.wipe),
                              ('kibernikto.telegram.handlers.reset.is_admin_id', lambda uid: uid == ADMIN.id)):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def message(self, chat_type: str, sender: User) -> Message:
        return Message(message_id=1, date=NOW, from_user=sender, text='/reset',
                       chat=Chat(id=200 if chat_type == 'private' else -100, type=chat_type)).as_(self.bot)

    def callback(self, data: str, chat_type: str, sender: User) -> CallbackQuery:
        prompt = self.message(chat_type, ADMIN.model_copy(update={'is_bot': True}))
        return CallbackQuery(id='1', from_user=sender, chat_instance='x', data=data, message=prompt).as_(self.bot)

    def sent_text(self) -> str:
        return self.bot.session.make_request.await_args.args[1].text

    async def press(self, data: str, chat_type: str, sender: User) -> tuple[AsyncMock, AsyncMock]:
        with patch.object(Message, 'edit_text', AsyncMock()) as edit, \
                patch.object(CallbackQuery, 'answer', AsyncMock()) as answer:
            await handle_reset_choice(self.callback(data, chat_type, sender))
        return edit, answer

    async def test_private_chat_asks_for_confirmation_without_wiping(self) -> None:
        await cmd_reset(self.message('private', USER))
        self.assertIn('cannot be undone', self.sent_text())
        self.wipe.assert_not_awaited()

    async def test_group_reset_is_admin_only(self) -> None:
        await cmd_reset(self.message('supergroup', USER))
        self.assertIn('Only admins', self.sent_text())
        await cmd_reset(self.message('supergroup', ADMIN))
        self.assertIn('cannot be undone', self.sent_text())

    async def test_group_reset_off_when_admin_commands_disabled(self) -> None:
        with patch.object(TELEGRAM_SETTINGS, 'ADMIN_COMMANDS_ALLOWED', False):
            await cmd_reset(self.message('supergroup', ADMIN))
        self.assertIn('Only admins', self.sent_text())

    async def test_confirm_wipes_the_prompt_chat(self) -> None:
        edit, _ = await self.press(CONFIRM, 'private', USER)
        self.assertEqual(self.wipe.await_args.args, (200,))
        edit.assert_awaited_once_with('✅ History and notes erased.')

    async def test_cancel_wipes_nothing(self) -> None:
        edit, _ = await self.press(CANCEL, 'private', USER)
        self.wipe.assert_not_awaited()
        edit.assert_awaited_once_with('Cancelled.')

    async def test_non_admin_cannot_confirm_in_group(self) -> None:
        edit, answer = await self.press(CONFIRM, 'supergroup', USER)
        self.wipe.assert_not_awaited()
        edit.assert_not_awaited()
        self.assertTrue(answer.await_args.kwargs['show_alert'])


class WiringTests(unittest.TestCase):
    def test_router_is_registered_before_conversation(self) -> None:
        import inspect
        from kibernikto.telegram.agent import telegram_app
        source = inspect.getsource(telegram_app.TelegramApp.from_agent)
        self.assertLess(source.index('include_router(reset_router)'), source.index('include_router(conversation_router)'))
        self.assertEqual(reset.reset_router.name, 'reset_router')


if __name__ == '__main__':
    unittest.main()
