"""Process-local request/reply correlation; only the existing Dispatcher receives updates."""
from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.types import Message, BufferedInputFile

from kibernikto.telegram.peer_protocol import PeerEnvelope, PeerProtocolError, download_envelope, FILENAME


@dataclass
class _Pending:
    future: asyncio.Future[str | PeerEnvelope]
    owner: asyncio.Task[object] | None
    message_id: int | None = None
    sending: bool = True
    envelope: PeerEnvelope | None = None
    bot: Bot | None = None
    deadline: float = 0
    receiving: bool = False
    download: asyncio.Task[PeerEnvelope] | None = None


class PeerHub:
    """Correlate private replies on one event loop, without persistent state.

    The newest max_tombstones completed requests suppress late/duplicate replies.
    Evicted IDs and sends whose HTTP response never supplied an ID are unknown;
    they cannot safely be distinguished from unrelated conversations.
    """

    def __init__(self, *, max_tombstones: int = 4096, max_pending: int = 256) -> None:
        if type(max_tombstones) is not int or max_tombstones <= 0:
            raise ValueError('max_tombstones must be a positive integer')
        if type(max_pending) is not int or max_pending <= 0:
            raise ValueError('max_pending must be a positive integer')
        self._max_tombstones = max_tombstones
        self._max_pending = max_pending
        self._pending: dict[tuple[int, int], list[_Pending]] = {}
        self._runs: set[asyncio.Task[object]] = set()
        self._completed: OrderedDict[tuple[int, int, int], None] = OrderedDict()
        self._changed = asyncio.Event()
        self._closed = False

    @property
    def tombstone_count(self) -> int:
        return len(self._completed)

    @property
    def pending_count(self) -> int:
        return sum(len(calls) for calls in self._pending.values())

    async def request(self, bot: Bot, peer: int, text: str, *, timeout: float,
                      envelope: PeerEnvelope | None = None) -> str | PeerEnvelope:
        if self._closed:
            raise RuntimeError('Peer hub is closed')
        if type(peer) is not int or not 0 < peer < 2 ** 52 or peer == bot.id:
            raise ValueError('Peer must be a positive Telegram user ID other than this bot')
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise ValueError('Prompt must contain 1–4096 characters and not be blank')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Timeout must be finite and positive')
        if self.pending_count >= self._max_pending:
            raise RuntimeError('Peer hub is at capacity')
        wire = envelope.encode() if envelope is not None else None
        pending = _Pending(asyncio.get_running_loop().create_future(), asyncio.current_task(),
                           envelope=envelope, bot=bot, deadline=asyncio.get_running_loop().time() + timeout)
        key = (bot.id, peer)
        calls = self._pending.setdefault(key, [])
        calls.append(pending)
        try:
            async with asyncio.timeout(timeout):
                if envelope is None:
                    sent = await bot.send_message(chat_id=peer, text=text, parse_mode=None)
                else:
                    sent = await bot.send_document(chat_id=peer, document=BufferedInputFile(wire, filename=FILENAME),
                                                   caption=envelope.caption, parse_mode=None)
                pending.message_id = sent.message_id
                pending.sending = False
                self._notify()
                return await pending.future
        finally:
            pending.sending = False
            self._notify()
            pending.future.cancel()
            if pending.message_id is not None:
                self._completed[(*key, pending.message_id)] = None
                while len(self._completed) > self._max_tombstones:
                    self._completed.popitem(last=False)
            calls.remove(pending)
            if not calls:
                self._pending.pop(key, None)
            if pending.download is not None:
                pending.download.cancel()
                await asyncio.gather(pending.download, return_exceptions=True)

    @asynccontextmanager
    async def track_run(self) -> AsyncIterator[None]:
        """Keep the entire remote run in the shutdown scope, including resolution."""
        if self._closed:
            raise RuntimeError('Peer hub is closed')
        owner = asyncio.current_task()
        assert owner is not None
        self._runs.add(owner)
        try:
            yield
        finally:
            self._runs.discard(owner)

    async def close(self) -> None:
        """Cancel and await remote runs, sends and waits; retain deduplication history."""
        self._closed = True
        owners = self._runs | {call.owner for calls in self._pending.values() for call in calls
                              if call.owner is not None}
        owners.discard(asyncio.current_task())
        for owner in owners:
            owner.cancel()
        await asyncio.gather(*owners, return_exceptions=True)

    async def accept(self, bot_id: int, message: Message) -> bool:
        """Wait for in-flight send IDs before deciding; never buffer/claim guesses."""
        if message.chat.type != ChatType.PRIVATE or message.from_user is None:
            return False
        if message.from_user.id != message.chat.id or message.reply_to_message is None:
            return False
        replied = message.reply_to_message
        if replied.from_user is None or replied.from_user.id != bot_id:
            return False
        if replied.chat.id != message.chat.id or replied.chat.type != ChatType.PRIVATE:
            return False

        if (bot_id, message.from_user.id, replied.message_id) in self._completed:
            return True
        calls = tuple(self._pending.get((bot_id, message.from_user.id), []))
        for pending in calls:
            if await self._resolve(pending, message):
                return True
        # Telegram can deliver an update before sendMessage's HTTP response returns.
        while any(pending.sending for pending in calls):
            await self._changed.wait()
            for pending in calls:
                if await self._resolve(pending, message):
                    return True
        return False

    def _notify(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    @staticmethod
    async def _resolve(pending: _Pending, message: Message) -> bool:
        if message.reply_to_message is None or message.reply_to_message.message_id != pending.message_id:
            return False
        if pending.envelope is not None:
            if pending.receiving or pending.future.done():
                return True
            expected = {f'KIBERNIKTO_PEER/1 {kind} {pending.envelope.request_id}' for kind in ('result', 'error')}
            if message.caption not in expected or message.document is None:
                return True  # Progress, text and unrelated documents never complete an envelope.
            pending.receiving = True
            try:
                async with asyncio.timeout_at(pending.deadline):
                    pending.download = asyncio.create_task(download_envelope(pending.bot, message))
                    try:
                        result = await asyncio.shield(pending.download)
                    except asyncio.CancelledError:
                        if pending.future.done():
                            return True
                        raise
                if result.kind not in ('result', 'error') or result.request_id != pending.envelope.request_id:
                    return True
                if not pending.future.done():
                    pending.future.set_result(result)
            except Exception as exc:
                if not pending.future.done():
                    error = PeerProtocolError('Peer response download or validation failed')
                    error.__cause__ = exc
                    pending.future.set_exception(error)
            finally:
                pending.receiving = False
            return True
        text = message.text or message.caption
        if text and not pending.future.done():
            pending.future.set_result(text)
        return True


current_peer_hub: ContextVar[PeerHub] = ContextVar('kibernikto_peer_hub')
