import logging
from typing import BinaryIO

from aiogram import types, enums, Bot as AIOGramBot
from kibernikto.utils.image import publish_image_file


async def get_message_text(message: types.Message, tg_bot: AIOGramBot):
    user_text = message.md_text
    if message.content_type == enums.ContentType.PHOTO and message.photo:
        logging.debug(f"processing photo from {message.from_user.full_name}")
        photo: types.PhotoSize = message.photo[-1]
        url = _process_photo(photo, tg_bot)
        user_text = f"{user_text} {url}"
    elif message.content_type == enums.ContentType.VOICE and message.voice:
        logging.debug(f"processing voice from {message.from_user.full_name}")
        pass
    elif message.content_type == enums.ContentType.DOCUMENT and message.document:
        logging.debug(f"processing document from {message.from_user.full_name}")
        document = message.document
        file_path = _process_document(document, tg_bot)
    elif message.content_type == enums.ContentType.TEXT and message.text:
        logging.debug(f"processing text from {message.from_user.full_name}")
        return message.text
    return user_text


async def _process_photo(photo: types.PhotoSize, tg_bot: AIOGramBot):
    file: types.File = await tg_bot.get_file(photo.file_id)
    file_path = file.file_path
    photo_file: BinaryIO = await tg_bot.download_file(file_path)
    # file_path = photo_file.file_path
    url = await publish_image_file(photo_file, photo.file_unique_id)
    logging.info(f"published image: {url}")
    return url


async def _process_document(document: types.Document, tg_bot: AIOGramBot):
    file: types.File = await tg_bot.get_file(document.file_id)
    file_path = file.file_path
    photo_file: BinaryIO = await tg_bot.download_file(file_path)
    file_path = photo_file.file_path
    return file_path
