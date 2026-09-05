import logging
import re
import uuid
from dataclasses import dataclass, field
from random import choice
from typing import List, Optional, Union, TYPE_CHECKING

from aiogram import Bot
from aiogram.enums import ChatType, ParseMode
from aiogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    ReplyParameters,
)
from aiogram.types.input_file import BufferedInputFile

from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.utils.text import (
    clear_text_format,
    markdown_to_html,
    prepare_for_MARKDOWN,
    split_text_by_sentences,
)

if TYPE_CHECKING:
    from pydantic_ai import AgentRunResult
    from pydantic_ai.messages import BinaryContent

logger = logging.getLogger(__name__)

MAX_CAPTION_LENGTH = 1023
MAX_MESSAGE_LENGTH = 4096

# aiogram media-group item classes keyed by media kind.
_MEDIA_CLASSES = {
    "photo": InputMediaPhoto,
    "video": InputMediaVideo,
    "audio": InputMediaAudio,
    "document": InputMediaDocument,
}


async def send_random_sticker(chat_id: int, sticker_list: List[str], bot: Bot) -> None:
    await bot.send_sticker(sticker=choice(sticker_list), chat_id=chat_id)


def is_reply(message: Message) -> bool:
    """True if ``message`` is a reply to one of the bot's own messages."""
    replied = message.reply_to_message
    return bool(replied and replied.from_user.id == message.bot.id)


def get_message_text(message: Message) -> Optional[str]:
    return message.text or message.caption or message.html_text or message.md_text


async def reply(
        message: Message,
        content: Union[str, "AgentRunResult", None] = None,
) -> str:
    """Reply to a Telegram message with text and any tool-produced media.

    ``content`` may be a plain ``str`` (e.g. used by access-denied messages) or
    an :class:`pydantic_ai.AgentRunResult`. In the latter case the model's text
    is sent together with every image and file present in the response — including
    binaries that tools produced, which ``KiberniktoAgent`` folds into the
    response as ``FilePart``s.

    Returns the text portion that was sent (empty string when only media was delivered).
    """
    # Only new, opted-in private peer requests may receive a response.
    if _is_private_bot(message) and not is_private_peer_request(message):
        return ""

    payload = _Payload.of(content)
    reply_mode = _uses_reply(message)

    if payload.has_media:
        return await _send_media(message, payload, reply_mode)

    await _send_text(message, payload.text, reply_mode)
    return payload.text


def _is_private_bot(message: Message) -> bool:
    """True when the sender is a bot in a private chat."""
    return bool(
        message.from_user
        and message.from_user.is_bot
        and message.chat.type == ChatType.PRIVATE
    )


def is_private_peer_request(message: Message) -> bool:
    """Opt in to new private bot requests; replies belong exclusively to the hub."""
    return bool(
        _is_private_bot(message)
        and message.from_user.id in TELEGRAM_SETTINGS.PEER_IDS
        and message.reply_to_message is None
    )


def _uses_reply(message: Message) -> bool:
    """Anchor humans and private peers; group bots post flat to avoid loops."""
    return _is_private_bot(message) or not (message.from_user and message.from_user.is_bot)


# ── Internals ─────────────────────────────────────────────────────────────────

@dataclass
class _Payload:
    """Normalised reply content: plain text plus any generated binaries."""

    text: str = ""
    images: List["BinaryContent"] = field(default_factory=list)
    files: List["BinaryContent"] = field(default_factory=list)

    @classmethod
    def of(cls, content: Union[str, "AgentRunResult", None]) -> "_Payload":
        if content is None:
            return cls()
        if isinstance(content, str):
            return cls(text=content)
        response = getattr(content, "response", None)
        return cls(
            text=getattr(content, "output", "") or "",
            images=list(getattr(response, "images", None) or []),
            files=_non_image_files(getattr(response, "files", None) or []),
        )

    @property
    def caption(self) -> str:
        return clear_text_format(self.text[:MAX_CAPTION_LENGTH])

    @property
    def has_media(self) -> bool:
        return bool(self.images or self.files)


async def _send_media(message: Message, payload: _Payload, reply_mode: bool) -> str:
    """Send generated media, carrying the caption where Telegram allows it.

    A single image rides along with the caption via ``reply_photo``. Anything
    else (multiple binaries, or non-image files) goes out as a media group,
    which has no shared caption — so the caption is sent as a separate text
    message first.

    ``payload.images`` is filtered by pydantic_ai via ``isinstance(_, BinaryImage)``,
    so a plain ``BinaryContent`` with an image media type never lands there.
    We split the combined media into photos / others by media kind so the
    image is delivered as a photo even if it didn't get narrowed upstream.
    """
    caption = payload.caption
    combined = payload.images + payload.files
    images = [b for b in combined if _media_kind(b) == "photo"]
    others = [b for b in combined if _media_kind(b) != "photo"]
    media = images + others

    if len(media) == 1 and images:
        try:
            await _deliver_photo(message, images[0], caption, reply_mode)
        except Exception as error:
            logger.error("Failed to send generated image: %s", error)
            if caption:
                await _send_text(message, caption, reply_mode)
        return caption

    if caption:
        await _send_text(message, caption, reply_mode)

    if media:
        try:
            await _deliver_media_group(message, media, reply_mode)
        except Exception as error:
            logger.error("Failed to send media group: %s", error)
            await _deliver_text(message, "[attachment delivery failed]", reply_mode, parse_mode=None)
    return caption


async def _send_text(message: Message, text: str, reply_mode: bool) -> None:
    """Send text, chunked to Telegram's limit, with a plain-text fallback."""
    if not text:
        return
    for chunk in split_text_by_sentences(text, MAX_MESSAGE_LENGTH):
        try:
            formatted = markdown_to_html(chunk) if TELEGRAM_SETTINGS.MARKDOWN_TO_HTML else prepare_for_MARKDOWN(chunk)
            parse_mode = ParseMode.HTML if TELEGRAM_SETTINGS.MARKDOWN_TO_HTML else ParseMode.MARKDOWN
            await _deliver_text(message, formatted, reply_mode, parse_mode)
        except Exception as error:
            logger.error("Error sending formatted message: %s", error)
            logger.debug("Problematic chunk: %s", chunk)
            await _deliver_text(message, clear_text_format(chunk), reply_mode, parse_mode=None)


async def _deliver_text(
        message: Message, text: str, reply_mode: bool, parse_mode: Optional[ParseMode]
) -> None:
    """Send one text chunk, replying to the message or posting flat."""
    if reply_mode and _is_private_bot(message):
        await message.bot.send_message(
            chat_id=message.chat.id, text=text, parse_mode=parse_mode,
            reply_parameters=ReplyParameters(message_id=message.message_id),
        )
    elif reply_mode:
        await message.reply(text=text, parse_mode=parse_mode)
    else:
        await message.bot.send_message(chat_id=message.chat.id, text=text, parse_mode=parse_mode)


async def _deliver_photo(
        message: Message, photo: "BinaryContent", caption: Optional[str], reply_mode: bool
) -> None:
    """Send a single photo, replying to the message or posting flat."""
    text = caption or None
    parse_mode = None
    if text and TELEGRAM_SETTINGS.MARKDOWN_TO_HTML:
        text = markdown_to_html(text)
        parse_mode = ParseMode.HTML
    if reply_mode:
        await message.reply_photo(photo=_as_input_file(photo), caption=text, parse_mode=parse_mode)
    else:
        await message.bot.send_photo(
            chat_id=message.chat.id, photo=_as_input_file(photo), caption=text, parse_mode=parse_mode
        )


async def _deliver_media_group(message: Message, media: List["BinaryContent"], reply_mode: bool) -> None:
    """Send independent media messages, replying or posting flat."""
    # Individual sends preserve order and work for single files and mixed media.
    for binary in media:
        kind = _media_kind(binary)
        sender = getattr(message.bot, f'send_{kind}')
        await sender(chat_id=message.chat.id, **{kind: _as_input_file(binary)},
                     reply_parameters=ReplyParameters(message_id=message.message_id) if reply_mode else None)


def _non_image_files(files: List["BinaryContent"]) -> List["BinaryContent"]:
    """Drop image-like binaries — those are delivered as photos, not documents."""
    return [binary for binary in files if _media_kind(binary) != "photo"]


def _media_kind(content: "BinaryContent") -> str:
    """Map a pydantic_ai ``BinaryContent`` to an aiogram media-group kind."""
    if content.is_audio:
        return "audio" if content.media_type in ('audio/mpeg', 'audio/mp4', 'audio/x-m4a') else "document"
    if content.is_video:
        return "video"
    if content.is_image:
        return "photo"
    return "document"


def _as_input_file(content: "BinaryContent") -> BufferedInputFile:
    return BufferedInputFile(file=content.data, filename=_filename_for(content))


def _as_input_media(content: "BinaryContent"):
    media_class = _MEDIA_CLASSES[_media_kind(content)]
    return media_class(media=_as_input_file(content))


def _filename_for(content: "BinaryContent", fallback_ext: str = "bin") -> str:
    filename = (getattr(content, 'vendor_metadata', None) or {}).get('filename')
    if isinstance(filename, str) and filename and len(filename) <= 128 and not any(
            c in filename for c in '/\\') and not any(ord(c) < 32 for c in filename) and filename not in ('.', '..'):
        return filename
    media_type = getattr(content, "media_type", "") or ""
    ext = re.sub(r"[^A-Za-z0-9]", "", media_type.split("/")[-1])[:8] or fallback_ext
    return f"kibernikto-{uuid.uuid4().hex[:8]}.{ext}"
