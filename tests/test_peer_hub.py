"""Offline peer correlation tests using real Dispatcher updates and HTTP-only mocks."""
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from typing import cast
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User

from kibernikto.telegram.middleware.middleware_peer import PeerMiddleware
from kibernikto.telegram.peer_hub import PeerHub, current_peer_hub


def message(message_id: int, *, peer: int = 200, sender: int | None = None,
            bot_id: int = 100, reply_id: int | None = None,
            chat_type: str = 'private', text: str | None = 'answer',
            caption: str | None = None) -> Message:
    chat = Chat(id=peer, type=chat_type)
    replied = None
    if reply_id is not None:
        replied = Message(message_id=reply_id, date=datetime.now(timezone.utc), chat=chat,
                          from_user=User(id=bot_id, is_bot=True, first_name='caller'),
                          text='question')
    return Message(message_id=message_id, date=datetime.now(timezone.utc), chat=chat,
                   from_user=User(id=peer if sender is None else sender,
                                  is_bot=True, first_name='peer'),
                   text=text, caption=caption, reply_to_message=replied)


class PeerHubTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(self.bot.session.close)
        self.hub = PeerHub()
        self.dispatcher = Dispatcher()
        self.dispatcher.message.outer_middleware(PeerMiddleware(self.hub))
        self.ordinary: list[Message] = []
        self.contexts: list[PeerHub] = []

        async def ordinary(event: Message) -> None:
            self.ordinary.append(event)
            self.contexts.append(current_peer_hub.get())

        self.dispatcher.message.register(ordinary)
        self.http = AsyncMock(return_value=message(10, sender=100))
        self.bot.session.make_request = self.http
        self.update_id = 0

    async def feed(self, event: Message, bot: Bot | None = None) -> None:
        self.update_id += 1
        await self.dispatcher.feed_update(bot or self.bot,
                                          Update(update_id=self.update_id, message=event))

    def request(self, *, timeout: float = 1, text: str = 'question',
                peer: int = 200) -> asyncio.Task[str]:
        task = asyncio.create_task(self.hub.request(self.bot, peer, text, timeout=timeout))
        self.addAsyncCleanup(self.cancel, task)
        return task

    async def cancel(self, task: asyncio.Task[object]) -> None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_fast_reply_for_second_send_does_not_wait_for_first_send(self) -> None:
        entered = asyncio.Event()
        release_first = asyncio.Event()
        release_second = asyncio.Event()

        async def send(bot: Bot, method: SendMessage, **kwargs: object) -> Message:
            if method.text == 'first':
                await release_first.wait()
                return message(10, sender=100)
            entered.set()
            await release_second.wait()
            return message(11, sender=100)

        self.http.side_effect = send
        first = self.request(text='first')
        second = self.request(text='second')
        await entered.wait()
        feed = asyncio.create_task(self.feed(message(21, reply_id=11)))
        self.addAsyncCleanup(self.cancel, feed)
        await asyncio.sleep(0)
        release_second.set()
        await asyncio.wait_for(feed, 0.1)
        self.assertEqual(await second, 'answer')
        self.assertFalse(first.done())
        release_first.set()
        await self.feed(message(22, reply_id=10))
        self.assertEqual(await first, 'answer')

    async def test_shutdown_cancels_sending_and_waiting_requests(self) -> None:
        entered = asyncio.Event()

        async def send(bot: Bot, method: SendMessage, **kwargs: object) -> Message:
            if method.text == 'sending':
                entered.set()
                await asyncio.Event().wait()
            return message(10, sender=100)

        self.http.side_effect = send
        waiting = self.request()
        sending = self.request(text='sending')
        await entered.wait()
        await self.hub.close()
        self.assertTrue(waiting.cancelled())
        self.assertTrue(sending.cancelled())
        self.assertEqual(self.hub.pending_count, 0)
        await self.feed(message(20, reply_id=10))
        self.assertEqual(self.ordinary, [])
        with self.assertRaises(RuntimeError):
            await self.hub.request(self.bot, 200, 'closed', timeout=1)
        self.assertEqual(self.http.await_count, 2)
        await self.hub.close()

    async def test_capacity_rejects_new_requests_before_send(self) -> None:
        self.hub = PeerHub(max_pending=1)
        first = self.request()
        await asyncio.sleep(0)
        with self.assertRaises(RuntimeError):
            await self.hub.request(self.bot, 201, 'overloaded', timeout=1)
        self.assertEqual(self.hub.pending_count, 1)
        self.assertEqual(self.http.await_count, 1)
        await self.cancel(first)
        self.assertEqual(self.hub.pending_count, 0)

    async def test_reply_target_chat_must_match_private_sender(self) -> None:
        task = self.request()
        await asyncio.sleep(0)
        event = message(20, reply_id=10)
        assert event.reply_to_message is not None
        replied = event.reply_to_message.model_copy(update={'chat': Chat(id=201, type='private')})
        event = event.model_copy(update={'reply_to_message': replied})
        await self.feed(event)
        self.assertFalse(task.done())
        self.assertEqual(len(self.ordinary), 1)
        await self.feed(message(21, reply_id=10))
        self.assertEqual(await task, 'answer')

    async def test_correlated_nontext_reply_never_reaches_ordinary_chat(self) -> None:
        task = self.request()
        await asyncio.sleep(0)
        await self.feed(message(20, reply_id=10, text=None))
        self.assertEqual(len(self.ordinary), 0)
        self.assertFalse(task.done())
        await self.feed(message(21, reply_id=10, text=None, caption='caption answer'))
        self.assertEqual(await task, 'caption answer')
        await self.feed(message(22, reply_id=10, text=None))
        self.assertEqual(len(self.ordinary), 0)

    def test_limits_must_be_positive_integers(self) -> None:
        for value in (0, -1, True, 1.5, float('inf')):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    PeerHub(max_pending=cast(int, value))
                with self.assertRaises(ValueError):
                    PeerHub(max_tombstones=cast(int, value))

    async def test_timeout_covers_http_send_and_releases_early_updates(self) -> None:
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def send(bot: Bot, method: SendMessage, **kwargs: object) -> Message:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            raise AssertionError('unreachable')

        self.http.side_effect = send
        task = self.request(timeout=0.03)
        await entered.wait()
        feed = asyncio.create_task(self.feed(message(20, reply_id=999)))
        with self.assertRaises(TimeoutError):
            await task
        await asyncio.wait_for(feed, 0.1)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.hub.pending_count, 0)
        self.assertEqual(self.hub.tombstone_count, 0)
        self.assertEqual(len(self.ordinary), 1)

    async def test_reply_after_timeout_is_consumed(self) -> None:
        with self.assertRaises(TimeoutError):
            await self.hub.request(self.bot, 200, 'question', timeout=0.02)
        self.assertEqual(self.hub.pending_count, 0)
        await self.feed(message(20, reply_id=10))
        self.assertEqual(len(self.ordinary), 0)

    async def test_reply_after_cancellation_is_consumed(self) -> None:
        task = self.request()
        await asyncio.sleep(0)
        await self.cancel(task)
        self.assertEqual(self.hub.pending_count, 0)
        await self.feed(message(20, reply_id=10))
        self.assertEqual(len(self.ordinary), 0)

    async def test_send_failure_releases_early_unrelated_update(self) -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def send(bot: Bot, method: SendMessage, **kwargs: object) -> Message:
            entered.set()
            await release.wait()
            raise OSError('offline HTTP failure')

        self.http.side_effect = send
        task = self.request()
        await entered.wait()
        feed = asyncio.create_task(self.feed(message(20, reply_id=999)))
        await asyncio.sleep(0)
        release.set()
        with self.assertRaisesRegex(OSError, 'offline HTTP failure'):
            await task
        await feed
        self.assertEqual(self.hub.pending_count, 0)
        self.assertEqual(self.hub.tombstone_count, 0)
        self.assertEqual(len(self.ordinary), 1)

    async def test_only_exact_private_reply_matches(self) -> None:
        task = self.request()
        await asyncio.sleep(0)
        unrelated = [
            message(20), message(21, reply_id=999),
            message(22, reply_id=10, sender=201),
            message(23, reply_id=10, peer=201),
            message(24, reply_id=10, bot_id=101),
            message(25, reply_id=10, chat_type='group'),
            message(26, reply_id=10).model_copy(update={'from_user': None}),
        ]
        for event in unrelated:
            await self.feed(event)
        other_bot = Bot('101:offline-test-token')
        self.addAsyncCleanup(other_bot.session.close)
        await self.feed(message(27, reply_id=10), bot=other_bot)
        self.assertEqual(len(self.ordinary), len(unrelated) + 1)
        self.assertFalse(task.done())
        await self.feed(message(28, reply_id=10))
        self.assertEqual(await task, 'answer')

    async def test_concurrent_requests_are_correlated_out_of_order(self) -> None:
        self.http.side_effect = [message(10, sender=100), message(11, sender=100)]
        first = self.request(text='first')
        second = self.request(text='second')
        await asyncio.sleep(0)
        await self.feed(message(20, reply_id=11, text='second result'))
        self.assertEqual(await second, 'second result')
        self.assertFalse(first.done())
        await self.feed(message(21, reply_id=10, text='first result'))
        self.assertEqual(await first, 'first result')
        self.assertEqual(self.hub.pending_count, 0)
        self.assertEqual(len(self.ordinary), 0)

    async def test_context_is_scoped_to_ordinary_handler(self) -> None:
        sentinel = PeerHub()
        token = current_peer_hub.set(sentinel)
        try:
            await self.feed(message(20))
            self.assertEqual(self.contexts, [self.hub])
            self.assertIs(current_peer_hub.get(), sentinel)
        finally:
            current_peer_hub.reset(token)

    async def test_cancelled_update_does_not_cancel_request(self) -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def send(bot: Bot, method: SendMessage, **kwargs: object) -> Message:
            entered.set()
            await release.wait()
            return message(10, sender=100)

        self.http.side_effect = send
        task = self.request()
        await entered.wait()
        feed = asyncio.create_task(self.feed(message(20, reply_id=10)))
        await asyncio.sleep(0)
        await self.cancel(feed)
        self.assertFalse(task.done())
        release.set()
        await self.feed(message(21, reply_id=10))
        self.assertEqual(await task, 'answer')

    async def test_cancellation_during_send_releases_unrelated_update(self) -> None:
        entered = asyncio.Event()

        async def send(bot: Bot, method: SendMessage, **kwargs: object) -> Message:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError('unreachable')

        self.http.side_effect = send
        task = self.request()
        await entered.wait()
        feed = asyncio.create_task(self.feed(message(20, reply_id=999)))
        await asyncio.sleep(0)
        await self.cancel(task)
        await asyncio.wait_for(feed, 0.1)
        self.assertEqual(self.hub.pending_count, 0)
        self.assertEqual(len(self.ordinary), 1)

    async def test_context_resets_when_handler_raises(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.message.outer_middleware(PeerMiddleware(self.hub))

        async def fail(event: Message) -> None:
            self.assertIs(current_peer_hub.get(), self.hub)
            raise ValueError('handler failed')

        dispatcher.message.register(fail)
        sentinel = PeerHub()
        token = current_peer_hub.set(sentinel)
        try:
            with self.assertRaisesRegex(ValueError, 'handler failed'):
                await dispatcher.feed_update(self.bot, Update(update_id=1, message=message(20)))
            self.assertIs(current_peer_hub.get(), sentinel)
        finally:
            current_peer_hub.reset(token)

    async def test_distinct_bots_can_use_the_same_outgoing_message_id(self) -> None:
        other = Bot('101:offline-test-token')
        self.addAsyncCleanup(other.session.close)
        other.session.make_request = AsyncMock(return_value=message(10, sender=101))
        first = self.request()
        second = asyncio.create_task(self.hub.request(other, 200, 'question', timeout=1))
        self.addAsyncCleanup(self.cancel, second)
        await asyncio.sleep(0)
        await self.feed(message(20, reply_id=10, bot_id=101, text='other'), bot=other)
        self.assertEqual(await second, 'other')
        self.assertFalse(first.done())
        await self.feed(message(21, reply_id=10, text='first'))
        self.assertEqual(await first, 'first')
        self.assertEqual(len(self.ordinary), 0)

    async def test_invalid_requests_are_rejected_before_http(self) -> None:
        invalid = [
            (200, '', 1), (200, ' \n', 1), (200, 'x' * 4097, 1),
            (200, None, 1), (200, 3, 1), (200, 'q', 0), (200, 'q', -1),
            (200, 'q', float('nan')), (200, 'q', float('inf')),
            (200, 'q', True), (200, 'q', '1'),
            (0, 'q', 1), (-200, 'q', 1), (100, 'q', 1),
            (True, 'q', 1), ('200', 'q', 1), (1 << 52, 'q', 1),
        ]
        for peer, prompt, timeout in invalid:
            with self.subTest(peer=peer, prompt=repr(prompt)[:30], timeout=timeout):
                with self.assertRaises((ValueError, TypeError)):
                    await asyncio.wait_for(
                        self.hub.request(self.bot, cast(int, peer), cast(str, prompt),
                                         timeout=cast(float, timeout)), 0.02)
        self.http.assert_not_awaited()
        self.assertEqual(self.hub.pending_count, 0)

    async def test_tombstones_have_a_bounded_retention_window(self) -> None:
        self.hub = PeerHub(max_tombstones=2)
        for outgoing in (10, 11, 12):
            self.http.return_value = message(outgoing, sender=100)
            task = self.request()
            await asyncio.sleep(0)
            self.assertTrue(await self.hub.accept(100, message(30, reply_id=outgoing)))
            await task
        self.assertEqual(self.hub.tombstone_count, 2)
        self.assertFalse(await self.hub.accept(100, message(31, reply_id=10)))
        self.assertTrue(await self.hub.accept(100, message(32, reply_id=11)))
        self.assertTrue(await self.hub.accept(100, message(33, reply_id=12)))
        self.assertFalse(await self.hub.accept(100, message(34, reply_id=999)))

    async def test_completed_request_swallows_duplicate_replies(self) -> None:
        request = self.request()
        await asyncio.sleep(0)
        await self.feed(message(20, reply_id=10))
        self.assertEqual(await request, 'answer')
        await self.feed(message(21, reply_id=10))
        self.assertEqual(self.ordinary, [])

    async def test_fast_reply_waits_for_send_without_eating_unrelated_reply(self) -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def send(bot: Bot, method: SendMessage, **kwargs: object) -> Message:
            entered.set()
            await release.wait()
            return message(10, sender=100)

        self.http.side_effect = send
        request = self.request()
        await entered.wait()
        unrelated = asyncio.create_task(self.feed(message(20, reply_id=999)))
        answer = asyncio.create_task(self.feed(message(21, reply_id=10)))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(unrelated, answer)
        self.assertEqual(await request, 'answer')
        self.assertEqual([event.message_id for event in self.ordinary], [20])
        self.assertEqual(self.hub.pending_count, 0)
