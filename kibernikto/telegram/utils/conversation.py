import logging
import random
from random import choice
from typing import List, Optional

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Message, FSInputFile
from kibernikto.utils.text import clear_text_format, split_text_by_sentences, prepare_for_MARKDOWN

logger = logging.getLogger(__name__)

MAX_CAPTION_LENGTH = 1023
MAX_MESSAGE_LENGTH = 4096


async def send_random_sticker(chat_id: int, sticker_list: List[str], bot: Bot):
    sticker_id = choice(sticker_list)

    await bot.send_sticker(
        sticker=sticker_id,
        chat_id=chat_id)


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
