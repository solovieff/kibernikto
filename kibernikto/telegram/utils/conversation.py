import logging
import re
import uuid
from dataclasses import dataclass, field
from random import choice
from typing import List, Optional, Union, TYPE_CHECKING

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import (
    FSInputFile,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from aiogram.types.input_file import BufferedInputFile

from kibernikto.utils.text import clear_text_format, split_text_by_sentences, prepare_for_MARKDOWN

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


async def send_random_sticker(chat_id: int, sticker_list: List[str], bot: Bot):
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
        file_attachment: Optional[FSInputFile] = None,
        image_attachment: Optional[FSInputFile] = None,
) -> str:
    """Reply to a Telegram message with text and any attachments.

    ``content`` may be a plain ``str`` (the legacy path used by the firewall
    middleware) or an :class:`pydantic_ai.AgentRunResult`. In the latter case
    the model's text is sent together with every image and file the model
    generated. ``file_attachment`` / ``image_attachment`` keep the legacy
    document/photo shortcuts working.

    Returns the text that was sent (empty when only media was delivered).
    """
    payload = _Payload.of(content)

    if file_attachment or image_attachment:
        return await _send_legacy_attachments(
            message, payload.caption, file_attachment, image_attachment
        )

    if payload.has_media:
        return await _send_media(message, payload)

    await _send_text(message, payload.text)
    return payload.text


# ─────────────────────────────────────────────────────────────────────
#  Internals
# ─────────────────────────────────────────────────────────────────────

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


async def _send_legacy_attachments(
        message: Message,
        caption: str,
        file_attachment: Optional[FSInputFile],
        image_attachment: Optional[FSInputFile],
) -> str:
    if file_attachment:
        await message.reply_document(document=file_attachment, caption=caption)
    if image_attachment:
        await message.reply_photo(photo=image_attachment, caption=caption)
    return caption


async def _send_media(message: Message, payload: _Payload) -> str:
    """Send generated media, carrying the caption where Telegram allows it.

    A single image rides along with the caption via ``reply_photo``. Anything
    else (multiple binaries, or non-image files) goes out as a media group,
    which has no shared caption — so the caption is sent as a separate text
    message first.
    """
    caption = payload.caption
    media = payload.images + payload.files

    if len(media) == 1 and payload.images:
        try:
            await message.reply_photo(photo=_as_input_file(media[0]), caption=caption or None)
        except Exception as error:
            logger.error(f"Failed to send generated image: {error}")
            if caption:
                await _send_text(message, caption)
        return caption

    if caption:
        await _send_text(message, caption)

    group = [_as_input_media(binary) for binary in media]
    if group:
        try:
            await message.answer_media_group(media=group)
        except Exception as error:
            logger.error(f"Failed to send media group: {error}")
            await message.reply("[attachment delivery failed]")
    return caption


async def _send_text(message: Message, text: str) -> None:
    """Send text, chunked to Telegram's limit, with a plain-text fallback."""
    if not text:
        return

    for chunk in split_text_by_sentences(text, MAX_MESSAGE_LENGTH):
        try:
            await message.reply(text=prepare_for_MARKDOWN(chunk), parse_mode=ParseMode.MARKDOWN)
        except Exception as error:
            logger.error(f"Error sending formatted message: {error}")
            logger.debug(f"Problematic chunk: {chunk}")
            await message.reply(text=clear_text_format(chunk))


def _non_image_files(files: List["BinaryContent"]) -> List["BinaryContent"]:
    """Drop image-like binaries; those are delivered as photos, not files."""
    return [binary for binary in files if _media_kind(binary) != "photo"]


def _media_kind(content: "BinaryContent") -> str:
    """Map a pydantic_ai BinaryContent to an aiogram media-group kind."""
    if content.is_audio:
        return "audio"
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
    media_type = getattr(content, "media_type", "") or ""
    ext = re.sub(r"[^A-Za-z0-9]", "", media_type.split("/")[-1])[:8] or fallback_ext
    return f"kibernikto-{uuid.uuid4().hex[:8]}.{ext}"
