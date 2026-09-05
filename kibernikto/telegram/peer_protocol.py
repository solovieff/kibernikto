"""Versioned atomic peer envelopes: inline bytes only, never URLs or local paths."""
from __future__ import annotations

import base64
import binascii
import json
import io

from aiogram import Bot
from aiogram.types import Message
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic_ai.messages import BinaryContent

MAX_WIRE_BYTES = 3 * 1024 * 1024
MAX_BINARY_BYTES = 2 * 1024 * 1024
MAX_PARTS = 8
MAX_TEXT = 65536
FILENAME = 'kibernikto-peer-v1.json'


class PeerProtocolError(ValueError):
    """Invalid, unsupported, incomplete or oversized peer transport."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PeerProtocolError('Duplicate JSON key')
        result[key] = value
    return result


class _BoundedBuffer(io.BytesIO):
    def write(self, data: bytes) -> int:
        if self.tell() + len(data) > MAX_WIRE_BYTES:
            raise PeerProtocolError('Downloaded envelope exceeds limit')
        return super().write(data)


async def download_envelope(bot: Bot, message: Message) -> PeerEnvelope:
    """Call only after access/correlation checks; trust only Bot API getFile paths."""
    doc = message.document
    if doc is None or doc.file_name != FILENAME or doc.mime_type != 'application/json':
        raise PeerProtocolError('Not a peer envelope document')
    if doc.file_size is None or not 0 < doc.file_size <= MAX_WIRE_BYTES:
        raise PeerProtocolError('Invalid envelope file size')
    file = await bot.get_file(doc.file_id)
    if not file.file_path or (file.file_size is not None and file.file_size > MAX_WIRE_BYTES):
        raise PeerProtocolError('Invalid Telegram file')
    buffer = _BoundedBuffer()
    await bot.download_file(file.file_path, destination=buffer)
    envelope = PeerEnvelope.decode(buffer.getvalue())
    if envelope.caption != message.caption:
        raise PeerProtocolError('Envelope caption mismatch')
    return envelope


@dataclass
class PeerEnvelope:
    kind: Literal['request', 'result', 'error']
    request_id: str
    text: str
    binaries: list[BinaryContent]

    @classmethod
    def create(cls, kind: Literal['request', 'result', 'error'], text: str,
               binaries: list[BinaryContent], *, request_id: str | None = None) -> PeerEnvelope:
        return cls(kind, request_id or uuid.uuid4().hex, text, binaries)

    @property
    def caption(self) -> str:
        return f'KIBERNIKTO_PEER/1 {self.kind} {self.request_id}'

    def encode(self) -> bytes:
        if len(self.binaries) > MAX_PARTS or sum(len(b.data) for b in self.binaries) > MAX_BINARY_BYTES:
            raise PeerProtocolError('Peer attachment limit exceeded')
        data = json.dumps({'version': 1, 'kind': self.kind, 'request_id': self.request_id,
                           'text': self.text, 'parts': [
                               {'data': base64.b64encode(b.data).decode('ascii'), 'media_type': b.media_type,
                                'filename': (b.vendor_metadata or {}).get('filename')}
                               for b in self.binaries], 'end': True}, ensure_ascii=False).encode('utf-8')
        self.decode(data)
        return data

    @classmethod
    def decode(cls, data: bytes) -> PeerEnvelope:
        if len(data) > MAX_WIRE_BYTES:
            raise PeerProtocolError('Peer envelope is too large')
        try:
            obj = json.loads(data, object_pairs_hook=_unique_object)
            return cls._decode_object(obj)
        except (ValueError, TypeError, KeyError, RecursionError, binascii.Error) as exc:
            raise PeerProtocolError('Invalid peer envelope') from exc

    @classmethod
    def _decode_object(cls, obj: dict) -> PeerEnvelope:
        if not isinstance(obj, dict) or set(obj) != {'version', 'kind', 'request_id', 'text', 'parts', 'end'}:
            raise PeerProtocolError('Unexpected envelope fields')
        if type(obj['version']) is not int or obj['version'] != 1 or obj['end'] is not True:
            raise PeerProtocolError('Unsupported version or incomplete envelope')
        if obj['kind'] not in ('request', 'result', 'error') or not isinstance(obj['request_id'], str) or not re.fullmatch(r'[0-9a-f]{32}', obj['request_id']):
            raise PeerProtocolError('Invalid kind or request ID')
        if not isinstance(obj['text'], str) or len(obj['text']) > MAX_TEXT:
            raise PeerProtocolError('Text limit exceeded')
        if not isinstance(obj['parts'], list) or len(obj['parts']) > MAX_PARTS:
            raise PeerProtocolError('Part count limit exceeded')
        binaries = [cls._decode_part(p) for p in obj['parts']]
        if sum(len(b.data) for b in binaries) > MAX_BINARY_BYTES:
            raise PeerProtocolError('Binary limit exceeded')
        return cls(obj['kind'], obj['request_id'], obj['text'], binaries)

    @staticmethod
    def _decode_part(part: dict) -> BinaryContent:
        if not isinstance(part, dict) or set(part) != {'data', 'media_type', 'filename'}:
            raise PeerProtocolError('Unexpected part fields')
        mime, name = part['media_type'], part['filename']
        if not isinstance(mime, str) or not re.fullmatch(r'[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+', mime) or len(mime) > 127:
            raise PeerProtocolError('Invalid MIME type')
        if name is not None and (not isinstance(name, str) or not name or len(name) > 128 or any(c in name for c in '/\\') or any(ord(c) < 32 for c in name) or name in ('.', '..')):
            raise PeerProtocolError('Unsafe filename')
        if not isinstance(part['data'], str):
            raise PeerProtocolError('Expected inline base64 bytes')
        data = base64.b64decode(part['data'], validate=True)
        return BinaryContent(data=data, media_type=mime, vendor_metadata={'filename': name} if name else None)
