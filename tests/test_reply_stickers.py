"""Offline coverage for probabilistic stickers after Telegram replies."""
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot
from aiogram.types import Chat, Message, User

from kibernikto.telegram.bridge import TelegramBridge
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.peer_protocol import PeerEnvelope


class ReplyStickerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = Bot('100:offline-test-token')
        self.message = Message(
            message_id=10,
            date=datetime.now(timezone.utc),
            chat=Chat(id=200, type='private'),
            from_user=User(id=200, is_bot=False, first_name='sender'),
            text='question',
        ).as_(self.bot)
        self.bridge = TelegramBridge(None)
        self.settings_patch = patch.multiple(
            TELEGRAM_SETTINGS, STICKER_IDS=['sticker-a', 'sticker-b'], STICKER_PROBABILITY=0.5,
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()

    async def test_sends_random_sticker_after_reply_when_probability_hits(self) -> None:
        events: list[str] = []
        reply_mock = AsyncMock(side_effect=lambda *_: events.append('reply'))
        sticker_mock = AsyncMock(side_effect=lambda **_: events.append('sticker'))
        with patch('kibernikto.telegram.bridge.reply', reply_mock), \
             patch('kibernikto.telegram.bridge.send_random_sticker', sticker_mock), \
             patch('kibernikto.telegram.bridge.random.random', return_value=0.49):
            await self.bridge.reply_to(self.message, 'answer')

        self.assertEqual(events, ['reply', 'sticker'])
        sticker_mock.assert_awaited_once_with(
            chat_id=self.message.chat.id,
            sticker_list=['sticker-a', 'sticker-b'],
            bot=self.bot,
        )

    async def test_skips_sticker_when_probability_does_not_hit(self) -> None:
        with patch('kibernikto.telegram.bridge.reply', new_callable=AsyncMock), \
             patch('kibernikto.telegram.bridge.send_random_sticker', new_callable=AsyncMock) as sticker, \
             patch('kibernikto.telegram.bridge.random.random', return_value=0.5):
            await self.bridge.reply_to(self.message, 'answer')

        sticker.assert_not_awaited()

    async def test_skips_sticker_when_list_is_empty(self) -> None:
        with patch.object(TELEGRAM_SETTINGS, 'STICKER_IDS', []), \
             patch('kibernikto.telegram.bridge.reply', new_callable=AsyncMock), \
             patch('kibernikto.telegram.bridge.send_random_sticker', new_callable=AsyncMock) as sticker, \
             patch('kibernikto.telegram.bridge.random.random', return_value=0.0):
            await self.bridge.reply_to(self.message, 'answer')

        sticker.assert_not_awaited()

    async def test_none_result_does_not_send_reply_or_sticker(self) -> None:
        with patch('kibernikto.telegram.bridge.reply', new_callable=AsyncMock) as reply_mock, \
             patch('kibernikto.telegram.bridge.send_random_sticker', new_callable=AsyncMock) as sticker, \
             patch('kibernikto.telegram.bridge.random.random') as random_value:
            await self.bridge.reply_to(self.message, None)

        reply_mock.assert_not_awaited()
        sticker.assert_not_awaited()
        random_value.assert_not_called()

    async def test_sticker_failure_does_not_fail_delivered_reply(self) -> None:
        reply_mock = AsyncMock()
        sticker_mock = AsyncMock(side_effect=RuntimeError('Telegram API failed'))
        with patch('kibernikto.telegram.bridge.reply', reply_mock), \
             patch('kibernikto.telegram.bridge.send_random_sticker', sticker_mock), \
             patch('kibernikto.telegram.bridge.random.random', return_value=0.0):
            with self.assertLogs('kibernikto.telegram.bridge', level='ERROR'):
                await self.bridge.reply_to(self.message, 'answer')

        reply_mock.assert_awaited_once_with(self.message, 'answer')
        sticker_mock.assert_awaited_once()

    async def test_redirected_reply_sends_sticker_to_redirected_chat(self) -> None:
        redirected = Message(
            message_id=20,
            date=datetime.now(timezone.utc),
            chat=Chat(id=300, type='private'),
            from_user=User(id=300, is_bot=False, first_name='redirect'),
            text='forwarded',
        ).as_(self.bot)
        result = SimpleNamespace(_reply_message=redirected)
        with patch('kibernikto.telegram.bridge.reply', new_callable=AsyncMock) as reply_mock, \
             patch('kibernikto.telegram.bridge.send_random_sticker', new_callable=AsyncMock) as sticker, \
             patch('kibernikto.telegram.bridge.random.random', return_value=0.0):
            await self.bridge.reply_to(self.message, result)

        reply_mock.assert_awaited_once_with(redirected, result)
        sticker.assert_awaited_once_with(
            chat_id=redirected.chat.id,
            sticker_list=['sticker-a', 'sticker-b'],
            bot=self.bot,
        )

    async def test_peer_envelope_does_not_send_sticker(self) -> None:
        peer_message = Message(
            message_id=30,
            date=datetime.now(timezone.utc),
            chat=Chat(id=200, type='private'),
            from_user=User(id=200, is_bot=True, first_name='peer'),
            text='peer request',
        ).as_(self.bot)
        self.bot.session.make_request = AsyncMock(return_value=peer_message)
        envelope = PeerEnvelope.create('result', 'answer', [], request_id='a' * 32)
        with patch.object(TELEGRAM_SETTINGS, 'PEER_IDS', [200]), \
             patch('kibernikto.telegram.bridge.send_random_sticker', new_callable=AsyncMock) as sticker:
            await self.bridge.reply_to(peer_message, envelope)

        self.bot.session.make_request.assert_awaited_once()
        sticker.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()