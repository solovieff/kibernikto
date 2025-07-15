import logging
import random
import time
from contextlib import contextmanager

from aiogram.enums import ParseMode
from aiogram.types import Message, FSInputFile

from .text import clear_text_format, split_text_by_sentences, prepare_for_MARKDOWN


@contextmanager
def timer(description="Execution time"):
    start = time.perf_counter()
    yield
    elapsed_time = time.perf_counter() - start
    print(f"{description}: {elapsed_time:.3f} seconds")
    return elapsed_time


async def reply(message: Message, reply_text: str, file_attachment: FSInputFile = None,
                image_attachment: FSInputFile = None):
    if not file_attachment and not image_attachment:
        await _text_reply(message=message, reply_text=reply_text)
        return reply_text

    caption = reply_text[:1023]
    caption = clear_text_format(caption)
    if file_attachment:
        await message.reply_document(document=file_attachment,
                                     caption=caption)
    if image_attachment:
        await message.reply_photo(photo=image_attachment,
                                  caption=caption)


async def _text_reply(message: Message, reply_text: str):
    from avatar.telegram.avatar_dispatcher import TELEGRAM_SETTINGS, send_random_sticker
    chunks = split_text_by_sentences(reply_text, TELEGRAM_SETTINGS.TG_MAX_MESSAGE_LENGTH)

    for chunk in chunks:

        try:
            await message.reply(
                text=prepare_for_MARKDOWN(chunk),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logging.error(f"{e}")
            print(chunk)
            await message.reply(
                text=clear_text_format(chunk)
            )
    if random.random() < 0.13:
        await message.bot.send_sticker(message.chat.id, random.choice(TELEGRAM_SETTINGS.TG_STICKERS))
