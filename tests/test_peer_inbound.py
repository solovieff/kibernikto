"""Offline coverage for opt-in private peer requests and correlated replies."""
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
from aiogram.types import Chat, Message, User
from pydantic_ai.models.test import TestModel

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
from kibernikto.telegram.config import TELEGRAM_SETTINGS, TelegramSettings
from kibernikto.telegram.utils.conversation import reply


class PeerSettingsTests(unittest.TestCase):
    def test_peer_ids_are_empty_by_default_and_loaded_from_env(self) -> None:
        with patch.dict(os.environ, {'TG_PEER_IDS': '[200, 300]'}):
            self.assertEqual(getattr(TelegramSettings(), 'PEER_IDS', None), [200, 300])
        with patch.dict(os.environ):
            os.environ.pop('TG_PEER_IDS', None)
            self.assertEqual(TelegramSettings().PEER_IDS, [])


def make_message(*, sender: int = 200, is_bot: bool = True,
                 chat_type: str = 'private', reply_id: int | None = None) -> Message:
    chat = Chat(id=sender if chat_type == 'private' else -100, type=chat_type)
    replied = None
    if reply_id is not None:
        replied = Message(message_id=reply_id, date=datetime.now(timezone.utc), chat=chat,
                          from_user=User(id=100, is_bot=True, first_name='recipient'), text='earlier')
    return Message(message_id=10, date=datetime.now(timezone.utc), chat=chat,
                   from_user=User(id=sender, is_bot=is_bot, first_name='sender'),
                   text='question', reply_to_message=replied)


class TextPreprocessor:
    async def process_tg_message(self, message: Message) -> list[str]:
        return [message.text] if message.text else []


class PeerInboundTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = Bot('100:offline-test-token')
        self.bot.session.make_request = AsyncMock(return_value=make_message())
        self.agent = TelegramAgent(model=TestModel(custom_output_text='answer'),
                                   pre_processor=TextPreprocessor(), history_storage=None)
        self.agent.build_deps = AsyncMock(return_value=TelegramDeps(is_personal=True))
        self.settings_patch = patch.multiple(TELEGRAM_SETTINGS, PEER_IDS=[200], BOT_MESSAGE_DELAY=0)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()

    async def test_allowlisted_private_request_runs_model_and_sends_correlated_reply(self) -> None:
        message = make_message().as_(self.bot)
        result = await self.agent.process_message(message)
        self.assertIsNotNone(result)
        self.assertEqual(result.output, 'answer')
        await self.agent.reply_to(message, result)
        self.bot.session.make_request.assert_awaited_once()
        sent = self.bot.session.make_request.await_args.args[1]
        self.assertEqual(sent.chat_id, message.chat.id)
        self.assertEqual(sent.text, 'answer')
        self.assertEqual(sent.reply_parameters.message_id, message.message_id)

    async def test_unknown_private_bots_never_reach_preprocessor_or_reply(self) -> None:
        for peer_ids in ([], [300]):
            with self.subTest(peer_ids=peer_ids), patch.object(TELEGRAM_SETTINGS, 'PEER_IDS', peer_ids):
                message = make_message().as_(self.bot)
                with patch.object(self.agent.pre_processor, 'process_tg_message', new_callable=AsyncMock) as process:
                    self.assertIsNone(await self.agent.process_message(message))
                    process.assert_not_awaited()
                self.assertEqual(await reply(message, 'answer'), '')
        self.agent.build_deps.assert_not_awaited()
        self.bot.session.make_request.assert_not_awaited()

    async def test_private_bot_replies_never_become_new_requests(self) -> None:
        # Both matched and unmatched/late replies are hub-only traffic.
        for reply_id in (1, 999):
            with self.subTest(reply_id=reply_id):
                message = make_message(reply_id=reply_id).as_(self.bot)
                with patch.object(self.agent.pre_processor, 'process_tg_message', new_callable=AsyncMock) as process:
                    self.assertIsNone(await self.agent.process_message(message))
                    process.assert_not_awaited()
                self.assertEqual(await reply(message, 'answer'), '')
        self.agent.build_deps.assert_not_awaited()
        self.bot.session.make_request.assert_not_awaited()

    async def test_private_human_replies_still_run_and_reply(self) -> None:
        message = make_message(sender=300, is_bot=False, reply_id=1).as_(self.bot)
        result = await self.agent.process_message(message)
        self.assertEqual(result.output, 'answer')
        await self.agent.reply_to(message, result)
        sent = self.bot.session.make_request.await_args.args[1]
        self.assertEqual(sent.reply_parameters.message_id, message.message_id)

    async def test_group_bots_keep_flat_replies_and_configured_delay(self) -> None:
        message = make_message(sender=300, chat_type='supergroup', reply_id=1).as_(self.bot)
        self.agent.build_deps.return_value = TelegramDeps(is_personal=False, username='peer')
        with patch.object(TELEGRAM_SETTINGS, 'BOT_MESSAGE_DELAY', 1), patch(
            'kibernikto.ai.agent.telegram.telegram_agent.asyncio.sleep', new_callable=AsyncMock
        ) as sleep, patch('kibernikto.ai.agent.telegram.telegram_agent.random.uniform', return_value=2):
            result = await self.agent.process_message(message)
        sleep.assert_awaited_once_with(2)
        self.assertEqual(result.output, 'answer')
        await self.agent.reply_to(message, result)
        sent = self.bot.session.make_request.await_args.args[1]
        self.assertIsNone(sent.reply_parameters)
        self.assertEqual(sent.chat_id, message.chat.id)

    async def test_group_humans_keep_anchored_replies(self) -> None:
        message = make_message(sender=300, is_bot=False, chat_type='group').as_(self.bot)
        self.agent.build_deps.return_value = TelegramDeps(is_personal=False, user_full_name='sender')
        result = await self.agent.process_message(message)
        self.assertEqual(result.output, 'answer')
        await self.agent.reply_to(message, result)
        sent = self.bot.session.make_request.await_args.args[1]
        self.assertEqual(sent.reply_parameters.message_id, message.message_id)

    async def test_firewall_still_blocks_new_peer_requests_without_access(self) -> None:
        from kibernikto.telegram.middleware.middleware_firewall import FirewallMiddleware

        handler = AsyncMock()
        message = make_message().as_(self.bot)
        with patch.multiple(TELEGRAM_SETTINGS, PUBLIC=False, MASTER_ID=100, MASTER_IDS=[]), self.assertLogs(
            'kibernikto.telegram.middleware.middleware_firewall', level='WARNING'
        ):
            await FirewallMiddleware()(handler, message, {})
        handler.assert_not_awaited()
        sent = self.bot.session.make_request.await_args.args[1]
        self.assertIn('Access is denied', sent.text)
        self.assertEqual(sent.reply_parameters.message_id, message.message_id)

    async def test_firewall_allows_opted_in_peer_with_master_access(self) -> None:
        from kibernikto.telegram.middleware.middleware_firewall import FirewallMiddleware

        handler = AsyncMock()
        message = make_message().as_(self.bot)
        with patch.multiple(TELEGRAM_SETTINGS, PUBLIC=False, MASTER_ID=100, MASTER_IDS=[200]):
            await FirewallMiddleware()(handler, message, {})
        handler.assert_awaited_once_with(message, {})
        self.bot.session.make_request.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
