"""Offline getChat context cache: TTL, invalidation on chat changes, update-only fallback, pinned text."""

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
from aiogram.types import Chat, ChatFullInfo, Message, User

from kibernikto.ai.agent.telegram import chat_context
from kibernikto.ai.agent.telegram.chat_context import forget_chat_context, get_chat_context
from kibernikto.telegram.handlers.conversation import conversation_router

NOW = datetime.now(timezone.utc)
CHAT = Chat(id=5, type='private', first_name='Vasya', username='vasya')


def full_chat(bio: str = 'pythonista', pinned: str | None = None) -> ChatFullInfo:
    pinned_message = Message(message_id=9, date=NOW, chat=CHAT, text=pinned) if pinned else None
    # model_construct: aiogram's required gift/colour fields churn between Bot API versions and are irrelevant here.
    return ChatFullInfo.model_construct(id=5, type='private', first_name='Vasya', username='vasya', bio=bio,
                                        pinned_message=pinned_message)


class ChatContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        chat_context._cache.clear()
        self.addCleanup(chat_context._cache.clear)
        self.bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(self.bot.session.close)
        self.message = Message(message_id=1, date=NOW, chat=CHAT, text='hi',
                               from_user=User(id=5, is_bot=False, first_name='Vasya')).as_(self.bot)

    async def test_get_chat_is_cached_within_ttl_and_refetched_after(self) -> None:
        with patch.object(Bot, 'get_chat', AsyncMock(return_value=full_chat())) as get_chat:
            first = await get_chat_context(self.message)
            self.assertEqual(await get_chat_context(self.message), first)
            self.assertEqual(get_chat.await_count, 1)
            with patch('kibernikto.ai.agent.telegram.chat_context.time.time',
                       return_value=chat_context._cache[(100, 5)][1] + chat_context._CHAT_REFRESH_SECONDS + 1):
                await get_chat_context(self.message)
            self.assertEqual(get_chat.await_count, 2)
        self.assertEqual(first, 'chat_type: private | full_name: Vasya | username: @vasya | bio: pythonista')

    async def test_pin_service_message_invalidates_and_pinned_text_is_shown(self) -> None:
        with patch.object(Bot, 'get_chat', AsyncMock(return_value=full_chat())):
            await get_chat_context(self.message)
        forget_chat_context(self.message)
        with patch.object(Bot, 'get_chat', AsyncMock(return_value=full_chat(pinned='x' * 300))) as get_chat:
            context = await get_chat_context(self.message)
        get_chat.assert_awaited_once()
        self.assertIn('pinned: ' + 'x' * 200 + '…', context)

    async def test_failed_get_chat_falls_back_to_update_chat_and_is_cached(self) -> None:
        with patch.object(Bot, 'get_chat', AsyncMock(side_effect=RuntimeError('tg down'))) as get_chat:
            self.assertEqual(await get_chat_context(self.message),
                             'chat_type: private | full_name: Vasya | username: @vasya')
            await get_chat_context(self.message)
        get_chat.assert_awaited_once()

    async def test_router_routes_pin_title_photo_to_invalidation_only(self) -> None:
        handler = next(h for h in conversation_router.message.handlers if h.callback.__name__ == 'handle_chat_changed')
        pinned = Message(message_id=2, date=NOW, chat=CHAT,
                         pinned_message=Message(message_id=9, date=NOW, chat=CHAT, text='rules')).as_(self.bot)
        for message, expected in ((pinned, True), (self.message, False)):
            with self.subTest(expected=expected):
                passed, _ = await handler.check(message)
                self.assertEqual(passed, expected)
        chat_context._cache[(100, 5)] = ('stale', 0.0)
        await handler.callback(pinned)
        self.assertNotIn((100, 5), chat_context._cache)


if __name__ == '__main__':
    unittest.main()
