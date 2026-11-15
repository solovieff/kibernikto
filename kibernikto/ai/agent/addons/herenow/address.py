"""Chat → here.now site label: readable, DNS-safe, derivable without any local storage."""

from __future__ import annotations

import re

LABEL_MAX = 63
_LABEL = re.compile(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$')
_ILLEGAL = re.compile(r'[^a-z0-9-]+')


def label_for_chat(username: str | None, chat_id: str | int | None) -> str:
    """Workspace label for a chat: the Telegram username when usable, else ``u<chat_id>``."""
    candidate = _ILLEGAL.sub('-', (username or '').strip().lower()).strip('-')[:LABEL_MAX].strip('-')
    if candidate and _LABEL.match(candidate):
        return candidate
    digits = re.sub(r'\D', '', str(chat_id or '')) or '0'
    return f'u{digits}'
