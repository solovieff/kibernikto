import logging
import random
import time
from contextlib import contextmanager
from typing import Optional

from aiogram.enums import ParseMode
from aiogram.types import Message, FSInputFile

from .text import clear_text_format, split_text_by_sentences, prepare_for_MARKDOWN

# Extracted constants
STICKER_PROBABILITY = 0.13
MAX_CAPTION_LENGTH = 1023
DEFAULT_MAX_MESSAGE_LENGTH = 4096

logger = logging.getLogger(__name__)


@contextmanager
def timer(description: str = "Execution time") -> float:
    """
    Context manager to measure execution time of code blocks.

    Args:
        description: Description for the timer output

    Returns:
        float: The elapsed time in seconds
    """
    start = time.perf_counter()
    yield
    elapsed_time = time.perf_counter() - start
    logger.info(f"{description}: {elapsed_time:.3f} seconds")
    return elapsed_time


async def reply(
        message: Message,
        reply_text: str,
        file_attachment: Optional[FSInputFile] = None,
        image_attachment: Optional[FSInputFile] = None
) -> str:
    """
    Reply to a Telegram message with text and optional attachments.

    Args:
        message: The message to reply to
        reply_text: The text content of the reply
        file_attachment: Optional document file to attach
        image_attachment: Optional image file to attach

    Returns:
        str: The sent text content
    """
    if not file_attachment and not image_attachment:
        await _text_reply(message=message, reply_text=reply_text)
        return reply_text

    # Handle attachments
    caption = clear_text_format(reply_text[:MAX_CAPTION_LENGTH])

    if file_attachment:
        await message.reply_document(document=file_attachment, caption=caption)

    if image_attachment:
        await message.reply_photo(photo=image_attachment, caption=caption)

    return caption


async def _text_reply(message: Message, reply_text: str) -> None:
    """
    Handle text-only replies, splitting long messages if needed.

    Args:
        message: The message to reply to
        reply_text: The text content of the reply
    """
    max_length = DEFAULT_MAX_MESSAGE_LENGTH
    chunks = split_text_by_sentences(reply_text, max_length)

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

    # Maybe send a random sticker
    if random.random() < STICKER_PROBABILITY:
        await _send_random_sticker(message)


async def _send_random_sticker(message: Message) -> None:
    """
    Send a random sticker from the configured sticker set.

    Args:
        message: The message to reply to with a sticker
    """
    from ..telegram.dispatcher import TELEGRAM_SETTINGS

    try:
        sticker = random.choice(TELEGRAM_SETTINGS.TG_STICKER_LIST)
        await message.bot.send_sticker(message.chat.id, sticker)
    except Exception as e:
        logger.error(f"Error sending sticker: {e}")
