"""Consume expected peer replies before conversation filters and access side effects."""
from collections.abc import Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, TelegramObject

from kibernikto.telegram.peer_hub import PeerHub, current_peer_hub


class PeerMiddleware(BaseMiddleware):
    def __init__(self, hub: PeerHub, *, accept_replies: bool = True) -> None:
        self.hub = hub
        self.accept_replies = accept_replies

    async def __call__(self, handler: Callable[..., Awaitable[object]],
                       event: TelegramObject, data: dict[str, object]) -> object:
        bot = data.get('bot')
        if (self.accept_replies and isinstance(event, Message) and isinstance(bot, Bot)
                and await self.hub.accept(bot.id, event)):
            return None
        token = current_peer_hub.set(self.hub)
        try:
            return await handler(event, data)
        finally:
            current_peer_hub.reset(token)
