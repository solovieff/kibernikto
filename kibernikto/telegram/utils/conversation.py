import logging
import re
import uuid
from random import choice
from typing import List, Optional, Union, TYPE_CHECKING

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Message, FSInputFile
from aiogram.types.input_file import BufferedInputFile

from kibernikto.utils.text import clear_text_format, split_text_by_sentences, prepare_for_MARKDOWN

if TYPE_CHECKING:
    from pydantic_ai import AgentRunResult
    from pydantic_ai.messages import BinaryContent

logger = logging.getLogger(__name__)

MAX_CAPTION_LENGTH = 1023
MAX_MESSAGE_LENGTH = 4096


async def send_random_sticker(chat_id: int, sticker_list: List[str], bot: Bot):
    sticker_id = choice(sticker_list)

    await bot.send_sticker(
        sticker=sticker_id,
        chat_id=chat_id)


def is_reply(message: Message):
    if message.reply_to_message and message.reply_to_message.from_user.id == message.bot.id:
        return True
    else:
        return False


def get_message_text(message: Message):
    return message.text or message.caption or message.html_text or message.md_text


async def reply(
        message: Message,
        reply_text: Union[str, "AgentRunResult", None] = None,
        file_attachment: Optional[FSInputFile] = None,
        image_attachment: Optional[FSInputFile] = None,
) -> str:
    """
    Reply to a Telegram message with text and optional attachments.

    Accepts either a plain ``str`` (the legacy mode used by
    :mod:`kibernikto.telegram.middleware.middleware_firewall`) or an
    :class:`pydantic_ai.AgentRunResult`. When an ``AgentRunResult`` is given, the
    helper:

    * pulls the final model text out of ``result.output``,
    * extracts any generated images (``ModelResponse.images``) and files
      (``ModelResponse.files`` — audio, video, PDFs, etc.) and sends them as
      Telegram attachments alongside the caption,
    * splits long text into ``MAX_MESSAGE_LENGTH``-bounded chunks and falls back
      to a plain-text send if Markdown parsing fails.

    Args:
        message: The message to reply to.
        reply_text: Text content or a :class:`AgentRunResult` produced by the agent.
        file_attachment: Optional document file to attach (legacy).
        image_attachment: Optional image file to attach (legacy).

    Returns:
        The text content that was sent (or the empty string when only media
        was sent).
    """
    text: str = ""
    generated_images: List["BinaryContent"] = []
    generated_files: List["BinaryContent"] = []

    # ── 1. Normalize input to (text, images, files) ───────────────────────
    if reply_text is None:
        text = ""
    elif isinstance(reply_text, str):
        text = reply_text
    else:
        # AgentRunResult path
        try:
            text = reply_text.output or ""
        except AttributeError:
            text = ""

        try:
            response = reply_text.response
        except AttributeError:
            response = None

        if response is not None:
            generated_images = list(getattr(response, "images", []) or [])
            generated_files = list(getattr(response, "files", []) or [])

    # ── 2. Pick attachment strategy ───────────────────────────────────────
    has_legacy_attachments = bool(file_attachment or image_attachment)
    has_generated_media = bool(generated_images) or bool(
        _pick_non_image_files(generated_files)
    )

    # ── 3. Media-first path: send a caption (≤1023 chars, plain text) and
    #       attach every generated image/file. ───────────────────────────
    if has_generated_media and not has_legacy_attachments:
        caption = clear_text_format((text or "")[:MAX_CAPTION_LENGTH])
        return await _send_media(
            message=message,
            caption=caption,
            images=generated_images,
            files=generated_files,
        )

    # ── 4. Legacy attachments path (middleware firewall). ────────────────
    if has_legacy_attachments:
        caption = clear_text_format((text or "")[:MAX_CAPTION_LENGTH])

        if file_attachment:
            await message.reply_document(document=file_attachment, caption=caption)

        if image_attachment:
            await message.reply_photo(photo=image_attachment, caption=caption)

        return caption

    # ── 5. Plain-text path (markdown → plain fallback, chunked). ─────────
    await _text_reply(message=message, reply_text=text or "")
    return text or ""


# ─────────────────────────────────────────────────────────────────────
#  Internals
# ─────────────────────────────────────────────────────────────────────

def _pick_non_image_files(files: List["BinaryContent"]) -> List["BinaryContent"]:
    """Filter out image-like BinaryContent items (we send them as photos)."""
    result: List["BinaryContent"] = []
    for f in files:
        try:
            if f.is_image():
                continue
        except Exception:
            pass
        result.append(f)
    return result


def _safe_filename(media_type: str, fallback_ext: str = "bin") -> str:
    """Build a sensible filename for a BufferedInputFile."""
    ext = (media_type or "").split("/")[-1] if "/" in (media_type or "") else ""
    ext = re.sub(r"[^A-Za-z0-9]", "", ext)[:8] or fallback_ext
    return f"kibernikto-{uuid.uuid4().hex[:8]}.{ext}"


async def _send_media(
        message: Message,
        caption: str,
        images: List["BinaryContent"],
        files: List["BinaryContent"],
) -> str:
    """
    Send a single reply that carries a caption and any number of images/files.

    Telegram's ``send_media_group`` is the only API that lets us attach more
    than one binary to a single message — but it doesn't accept a caption
    (per-item captions only). So for a single image we use ``reply_photo``
    (carries the caption) and for everything else we use ``send_media_group``
    (no shared caption — we send a separate text chunk first if needed).
    """
    # All non-image files (audio, video, PDFs, …) plus any extra images
    # beyond the first go into a media group. The first image, if any, rides
    # along with the caption via reply_photo.
    first_image = images[0] if images else None
    group_items: List[InputMediaLike] = []

    if first_image is not None and len(images) + len(files) == 1:
        # Single image → reply_photo with the caption.
        try:
            await message.reply_photo(
                photo=_binary_to_input(first_image),
                caption=caption or None,
            )
        except Exception as e:
            logger.error(f"Failed to send generated image: {e}")
            if caption:
                await _text_reply(message=message, reply_text=caption)
        return caption

    # Multi-item case: caption goes out as a separate text chunk, then a
    # media group with all the binaries.
    if caption:
        await _text_reply(message=message, reply_text=caption)

    for img in images:
        group_items.append(_binary_to_input_media(img, kind="photo"))
    for f in _pick_non_image_files(files):
        kind = _media_kind(f)
        group_items.append(_binary_to_input_media(f, kind=kind))

    if not group_items:
        return caption

    try:
        await message.answer_media_group(media=group_items)
    except Exception as e:
        logger.error(f"Failed to send media group: {e}")
        # Fallback: at least tell the user something went wrong.
        await message.reply("[attachment delivery failed]")

    return caption


# Tiny alias to keep the type-hint readable without importing the heavy
# aiogram types module at module load time.
InputMediaLike = object


def _binary_to_input(content: "BinaryContent") -> BufferedInputFile:
    """Wrap a pydantic_ai BinaryContent in an aiogram BufferedInputFile."""
    data: bytes = content.data  # type: ignore[attr-defined]
    return BufferedInputFile(
        file=data,
        filename=_safe_filename(getattr(content, "media_type", "") or ""),
    )


def _binary_to_input_media(content: "BinaryContent", kind: str) -> InputMediaLike:
    """Build an aiogram ``InputMedia*`` object for a media group."""
    from aiogram.types import (  # local import — keep module load cheap
        InputMediaPhoto,
        InputMediaVideo,
        InputMediaAudio,
        InputMediaDocument,
    )

    data: bytes = content.data  # type: ignore[attr-defined]
    filename = _safe_filename(getattr(content, "media_type", "") or "")
    file = BufferedInputFile(file=data, filename=filename)

    cls = {
        "photo": InputMediaPhoto,
        "video": InputMediaVideo,
        "audio": InputMediaAudio,
    }.get(kind, InputMediaDocument)
    return cls(media=file)


def _media_kind(content: "BinaryContent") -> str:
    """Map a pydantic_ai BinaryContent to an aiogram media-group kind."""
    try:
        if content.is_audio():
            return "audio"
        if content.is_video():
            return "video"
        if content.is_image():
            return "photo"
    except Exception:
        pass
    return "document"


async def _text_reply(message: Message, reply_text: str) -> None:
    """
    Handle text-only replies, splitting long messages if needed.

    Args:
        message: The message to reply to
        reply_text: The text content of the reply
    """
    if not reply_text:
        return

    chunks = split_text_by_sentences(reply_text, MAX_MESSAGE_LENGTH)

    for chunk in chunks:
        try:
            await message.reply(
                text=prepare_for_MARKDOWN(chunk),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Error sending formatted message: {e}")
            logger.debug(f"Problematic chunk: {chunk}")
            await message.reply(text=clear_text_format(chunk))
