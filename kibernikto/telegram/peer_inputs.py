"""Opt-in capture of current Telegram attachments without preprocessing."""
from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from aiogram.types import Audio, Document, Message, PhotoSize, Voice
from pydantic_ai.messages import BinaryContent

from .peer_protocol import MAX_BINARY_BYTES, MAX_PARTS, PeerProtocolError

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


class _BoundedBuffer(BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def write(self, data: ReadableBuffer) -> int:
        _check_size(self.tell() + memoryview(data).nbytes, self.limit)
        return super().write(data)


def _check_size(size: int | None, remaining: int) -> None:
    if size is not None and size > remaining:
        raise PeerProtocolError('Peer input binary limit exceeded')


def _safe_filename(name: str | None, fallback: str) -> str:
    if (not name or name in ('.', '..') or len(name) > 128
            or any(c in name for c in '/\\') or any(ord(c) < 32 for c in name)):
        return fallback
    return name


async def capture_peer_inputs(message: Message) -> list[BinaryContent]:
    """Capture current-message originals; callers opt in by invoking this helper.

    Return photo, voice, audio and document bytes in that order. Safe original
    filenames survive in vendor_metadata; missing/unsafe names use fixed defaults.
    Raise PeerProtocolError for limits or missing Telegram paths. Download errors
    and cancellation propagate; failures never return a partial attachment list.
    """
    media: list[tuple[PhotoSize | Voice | Audio | Document, str, str]] = []
    if message.photo:
        media.append((message.photo[-1], 'image/jpeg', 'photo.jpg'))
    if message.voice:
        media.append((message.voice, 'audio/ogg', 'voice.ogg'))
    if message.audio:
        media.append((message.audio, message.audio.mime_type or 'application/octet-stream',
                      _safe_filename(message.audio.file_name, 'audio.bin')))
    if message.document:
        media.append((message.document, message.document.mime_type or 'application/octet-stream',
                      _safe_filename(message.document.file_name, 'document.bin')))
    if len(media) > MAX_PARTS:
        raise PeerProtocolError('Peer input part count limit exceeded')
    binaries: list[BinaryContent] = []
    remaining = MAX_BINARY_BYTES
    for attachment, mime, name in media:
        _check_size(attachment.file_size, remaining)
        file = await message.bot.get_file(attachment.file_id)
        _check_size(file.file_size, remaining)
        if not file.file_path:
            raise PeerProtocolError('Telegram file path is missing')
        with _BoundedBuffer(remaining) as destination:
            await message.bot.download_file(file.file_path, destination=destination)
            data = destination.getvalue()
        binaries.append(BinaryContent(data=data, media_type=mime, vendor_metadata={'filename': name}))
        remaining -= len(data)
    return binaries
