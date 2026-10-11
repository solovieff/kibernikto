"""Offline regressions for firewall and subscription middleware with real aiogram objects."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot
from aiogram.types import Chat, Message, User

from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.middleware.middleware_firewall import FirewallMiddleware
from kibernikto.telegram.middleware.middleware_subscription import SubscriptionMiddleware, SUBSCRIPTION_SETTINGS

MASTER = 1001
STRANGER = 2002
GROUP = -3003


def make_message(user_id: int, chat_id: int, chat_type: str, text: str = 'hi') -> Message:
    user = User(id=user_id, is_bot=False, first_name='u', username=f'u{user_id}')
    chat = Chat(id=chat_id, type=chat_type, title='g' if chat_type != 'private' else None)
    return Message(message_id=1, date=datetime.now(timezone.utc), chat=chat, from_user=user, text=text)


class ErrorReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_sends_plain_text_so_exception_angle_brackets_do_not_break_html(self) -> None:
        from kibernikto.telegram.middleware.middleware_service import ErrorsMiddleware

        with patch.object(TELEGRAM_SETTINGS, 'SERVICE_GROUP_ID', -4242):
            middleware = ErrorsMiddleware()
        bot = AsyncMock()
        exc = RuntimeError('<ModelHTTPError: status_code: 404>')
        message = make_message(STRANGER, STRANGER, 'private', text='draw')
        await middleware._report(bot=bot, user_message=message, exc=exc)
        self.assertIsNone(bot.send_message.await_args.kwargs['parse_mode'])
        self.assertIn('<ModelHTTPError', bot.send_message.await_args.args[1])
        self.assertLessEqual(len(bot.send_message.await_args.args[1]), 4096)


class FakeHandler:
    """Plain async callable: aiogram-style flags are read from registered callables."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, event, data):
        self.calls += 1
        return 'handled'


class FirewallTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.middleware = FirewallMiddleware()
        self.handler = FakeHandler()
        self.reply = patch('kibernikto.telegram.middleware.middleware_firewall.reply', new=AsyncMock()).start()
        self.addCleanup(patch.stopall)
        patch.multiple(TELEGRAM_SETTINGS, MASTER_ID=MASTER, MASTER_IDS=[MASTER],
                       PUBLIC=False, FRIEND_GROUP_IDS=[]).start()

    async def run_middleware(self, message: Message):
        return await self.middleware(self.handler, message, {})

    async def test_private_stranger_is_denied_and_told_so(self) -> None:
        self.assertIsNone(await self.run_middleware(make_message(STRANGER, STRANGER, 'private')))
        self.assertEqual(self.handler.calls, 0)
        self.reply.assert_awaited_once()

    async def test_master_passes_private_when_closed(self) -> None:
        self.assertEqual(await self.run_middleware(make_message(MASTER, MASTER, 'private')), 'handled')
        self.reply.assert_not_awaited()

    async def test_public_mode_lets_strangers_in(self) -> None:
        with patch.object(TELEGRAM_SETTINGS, 'PUBLIC', True):
            self.assertEqual(await self.run_middleware(make_message(STRANGER, STRANGER, 'private')), 'handled')

    async def test_group_without_allowlist_is_open(self) -> None:
        self.assertEqual(await self.run_middleware(make_message(STRANGER, GROUP, 'supergroup')), 'handled')

    async def test_group_outside_allowlist_is_silently_dropped(self) -> None:
        with patch.object(TELEGRAM_SETTINGS, 'FRIEND_GROUP_IDS', [-9999]):
            self.assertIsNone(await self.run_middleware(make_message(STRANGER, GROUP, 'supergroup')))
        self.assertEqual(self.handler.calls, 0)
        self.reply.assert_not_awaited()

    async def test_group_inside_allowlist_is_allowed(self) -> None:
        with patch.object(TELEGRAM_SETTINGS, 'FRIEND_GROUP_IDS', [GROUP]):
            self.assertEqual(await self.run_middleware(make_message(STRANGER, GROUP, 'supergroup')), 'handled')

    async def test_event_without_message_is_dropped(self) -> None:
        self.assertIsNone(await self.middleware(self.handler, object(), {}))
        self.assertEqual(self.handler.calls, 0)



class SubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.middleware = SubscriptionMiddleware()
        self.handler = FakeHandler()
        self.bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(self.bot.session.close)
        self.check_sub = patch('kibernikto.telegram.middleware.middleware_subscription.check_sub',
                               new=AsyncMock(return_value=False)).start()
        patch('kibernikto.telegram.middleware.middleware_subscription.create_payment_link',
              new=AsyncMock(return_value='https://t.me/invoice/x')).start()
        self.answer = patch.object(Message, 'answer', new=AsyncMock()).start()
        self.addCleanup(patch.stopall)
        self.message = make_message(STRANGER, STRANGER, 'private', text='tell me a story')

    async def run_middleware(self, message: Message):
        return await self.middleware(self.handler, message, {'bot': self.bot})

    async def test_unpaid_private_user_gets_payment_prompt_and_no_llm(self) -> None:
        self.assertIsNone(await self.run_middleware(self.message))
        self.assertEqual(self.handler.calls, 0)
        self.answer.assert_awaited_once()
        self.assertIsNotNone(self.answer.await_args.kwargs['reply_markup'])

    async def test_paid_user_reaches_handler(self) -> None:
        self.check_sub.return_value = True
        self.assertEqual(await self.run_middleware(self.message), 'handled')
        self.answer.assert_not_awaited()

    async def test_commands_bypass_subscription(self) -> None:
        command = make_message(STRANGER, STRANGER, 'private', text='/start')
        self.assertEqual(await self.run_middleware(command), 'handled')
        self.check_sub.assert_not_awaited()

    async def test_groups_bypass_subscription(self) -> None:
        group = make_message(STRANGER, GROUP, 'supergroup', text='hello')
        self.assertEqual(await self.run_middleware(group), 'handled')
        self.check_sub.assert_not_awaited()

    async def test_successful_payment_message_bypasses_subscription(self) -> None:
        paid = self.message.model_copy(update={'successful_payment': object()})
        self.assertTrue(SubscriptionMiddleware.can_skip_subscription(paid))

    async def test_disabled_flag_registers_no_middleware(self) -> None:
        from aiogram import Router
        router = Router()
        with patch.object(SUBSCRIPTION_SETTINGS, 'ENABLED', False):
            SubscriptionMiddleware.apply_if_needed(router)
        self.assertEqual(len(router.message.outer_middleware), 0)


if __name__ == '__main__':
    unittest.main()
