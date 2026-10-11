"""Check history image links: HEAD each ``ImageUrl``, store live ones once, replace dead ones with text.

Only ``ImageUrl`` parts with a ``media_ref`` in ``vendor_metadata`` are stored locally; the
rest are checked by HEAD and replaced with text when the link is dead. Nothing is read back
from the media store here — the store is write-only for now.
"""

import logging
from dataclasses import replace
from typing import Awaitable, Callable

import aiohttp
from pydantic_ai.messages import ImageUrl, ModelMessage, ModelRequest, UserContent, UserPromptPart

logger = logging.getLogger(__name__)

DEAD_LINK_TEXT = "[image no longer available]"
_HEAD_TIMEOUT_SECONDS = 10

Head = Callable[[str], Awaitable[bool]]
Fetch = Callable[[str], Awaitable[bytes]]
Exists = Callable[[str, str], Awaitable[bool]]  # (store_name, media_ref)
Save = Callable[[str, str, bytes], Awaitable[None]]  # (store_name, media_ref, data)


async def head_alive(url: str) -> bool:
    """True when the URL answers 2xx to a HEAD request."""
    try:
        timeout = aiohttp.ClientTimeout(total=_HEAD_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.head(url, allow_redirects=True) as response:
                return 200 <= response.status < 300
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        logger.info("Image link check failed for %s: %s", url, exc)
        return False


async def fetch_bytes(url: str) -> bytes:
    """Download the URL body (only called for live links not yet in the media store)."""
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()


async def _check_item(item: UserContent, *, head: Head, exists: Exists, fetch: Fetch, save: Save,
                      chat_id: int) -> UserContent:
    """Return the item to keep, or a text replacement when the link is dead."""
    if not isinstance(item, ImageUrl):
        return item
    metadata = item.vendor_metadata or {}
    ref = metadata.get("media_ref")
    store = metadata.get("media_store", "default")
    # HEAD always: a stored copy doesn't prove the link is alive, and the model gets the URL.
    if not await head(item.url):
        logger.info("Dead image link in history for chat %s, replaced with text", chat_id)
        return DEAD_LINK_TEXT
    if ref is None or await exists(store, ref):
        return item
    await save(store, ref, await fetch(item.url))
    return item


async def check_history_images(
    messages: list[ModelMessage],
    *,
    chat_id: int,
    exists: Exists,
    save: Save,
    head: Head = head_alive,
    fetch: Fetch = fetch_bytes,
) -> tuple[list[ModelMessage], bool]:
    """Walk the history; return ``(messages, changed)`` with dead image links replaced by text."""
    changed = False
    result: list[ModelMessage] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            result.append(message)
            continue
        new_parts = []
        for part in message.parts:
            if not isinstance(part, UserPromptPart) or not isinstance(part.content, list):
                new_parts.append(part)
                continue
            new_content: list[UserContent] = []
            for item in part.content:
                checked = await _check_item(item, head=head, exists=exists, fetch=fetch, save=save, chat_id=chat_id)
                changed = changed or checked is not item
                new_content.append(checked)
            new_parts.append(replace(part, content=new_content))
        result.append(replace(message, parts=new_parts))
    return result, changed
