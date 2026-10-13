"""Chat enrichment via Telegram getChat, cached in process memory (nothing persisted)."""

import logging
import time
from collections import OrderedDict

from aiogram.enums import ChatType
from aiogram.types import Chat, ChatFullInfo, Message

logger = logging.getLogger(__name__)

_CHAT_REFRESH_SECONDS = 600.0
_CACHE_LIMIT = 4096
_PINNED_CHARS = 200

# (bot_id, chat_id) -> (context line, fetched_at); LRU-bounded, lost on restart by design.
_cache: OrderedDict[tuple[int, int], tuple[str, float]] = OrderedDict()


def _pinned(chat: Chat | ChatFullInfo) -> str | None:
    """Short text of the chat's pinned message, if getChat returned one."""
    pinned = getattr(chat, "pinned_message", None)
    text = pinned and (pinned.text or pinned.caption)
    if not text:
        return None
    return text if len(text) <= _PINNED_CHARS else text[:_PINNED_CHARS] + "…"


def format_chat_context(chat: Chat | ChatFullInfo) -> str:
    """Compact one-line chat facts — key: value | key: value; full-only fields skipped on a plain Chat."""
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        parts = ["chat_type: group"]
        if chat.title:
            parts.append(f"title: {chat.title}")
        if chat.username:
            parts.append(f"username: @{chat.username}")
        if getattr(chat, "description", None):
            parts.append(f"chat_info: {chat.description}")
        if getattr(chat, "member_count", None):
            parts.append(f"members: {chat.member_count}")
        if pinned := _pinned(chat):
            parts.append(f"pinned: {pinned}")
        return " | ".join(parts)
    name = " ".join(filter(None, [chat.first_name, chat.last_name])) or "unknown"
    parts = ["chat_type: private", f"full_name: {name}"]
    if chat.username:
        parts.append(f"username: @{chat.username}")
    if getattr(chat, "bio", None):
        parts.append(f"bio: {chat.bio}")
    birthdate = getattr(chat, "birthdate", None)
    if birthdate:
        bd = f"{birthdate.day:02d}.{birthdate.month:02d}"
        if getattr(birthdate, "year", None):
            bd += f".{birthdate.year}"
        parts.append(f"birthday: {bd}")
    if pinned := _pinned(chat):
        parts.append(f"pinned: {pinned}")
    return " | ".join(parts)


def _key(message: Message) -> tuple[int, int]:
    return message.bot.id if message.bot else 0, message.chat.id


async def get_chat_context(message: Message) -> str:
    """Chat facts for the prompt: getChat at most once per TTL per chat, update-only fallback on failure."""
    key = _key(message)
    cached = _cache.get(key)
    if cached and time.time() - cached[1] < _CHAT_REFRESH_SECONDS:
        _cache.move_to_end(key)
        return cached[0]
    try:
        context = format_chat_context(await message.bot.get_chat(message.chat.id))
    except Exception as error:
        logger.warning("Failed to fetch full chat %s: %s", message.chat.id, error)
        context = format_chat_context(message.chat)  # Cached too: a failing getChat is not retried per message.
    _cache[key] = (context, time.time())
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)
    return context


def forget_chat_context(message: Message) -> None:
    """Drop the cached facts so the next run re-reads getChat (pin, title or photo changed)."""
    _cache.pop(_key(message), None)
