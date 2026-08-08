"""Chat enrichment via Telegram getChat (TTL-cached in chat_data bucket)."""

import logging
import time
from typing import Optional

from aiogram.enums import ChatType
from aiogram.types import ChatFullInfo, Message

from kibernikto.storage.file.chat_data import chat_data

logger = logging.getLogger(__name__)

_CHAT_REFRESH_SECONDS = 600.0


def format_chat_context(chat: ChatFullInfo) -> Optional[str]:
    """Compact one-line chat facts from a full Chat — key: value | key: value."""
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        parts = ["chat_type: group"]
        if chat.title:
            parts.append(f"title: {chat.title}")
        if chat.username:
            parts.append(f"username: @{chat.username}")
        if chat.description:
            parts.append(f"chat_info: {chat.description}")
        if getattr(chat, "member_count", None):
            parts.append(f"members: {chat.member_count}")
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
    return " | ".join(parts)


async def refresh_chat_context(message: Message) -> None:
    """Persist full getChat facts into the chat bucket, refreshing when missing or stale."""
    info = await chat_data.load(message.chat.id)
    updated_at = info.client_app_info_updated_at or 0
    if info.client_app_info and time.time() - updated_at < _CHAT_REFRESH_SECONDS:
        return
    try:
        chat = await message.bot.get_chat(message.chat.id)
    except Exception as error:
        logger.warning("Failed to fetch full chat %s: %s", message.chat.id, error)
        return
    info.client_app_info = format_chat_context(chat) or info.client_app_info
    info.client_app_info_updated_at = time.time()
    await chat_data.save(message.chat.id, info)
