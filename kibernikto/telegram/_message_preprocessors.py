import logging
from typing import BinaryIO, Literal

from aiogram import types, enums, Bot as AIOGramBot
from openai import AsyncOpenAI
from openai.resources.audio import AsyncTranscriptions
from pydantic_settings import BaseSettings

from kibernikto.utils.image import publish_image_file


class PreprocessorSettings(BaseSettings):
    VOICE_PROCESSOR: Literal["openai", "local"] | None = None
    IMAGE_SUMMARIZATION_OPENAI_API_KEY: str | None = None
    VOICE_OPENAI_API_KEY: str | None = None
    VOICE_OPENAI_API_MODEL: str = "whisper-1"
    VOICE_OPENAI_API_BASE_URL: str | None = None
    VOICE_FILE_LOCATION: str = "/tmp/tg_voices"


SETTINGS = PreprocessorSettings()


async def get_message_text(message: types.Message, tg_bot: AIOGramBot):
    """
    returns text to be processed by AI and it's plugins

    :param message:
    :param tg_bot:
    :return:
    """
    user_text = message.md_text
    if message.content_type == enums.ContentType.PHOTO and message.photo:
        if SETTINGS.IMAGE_SUMMARIZATION_OPENAI_API_KEY is not None:
            logging.debug(f"processing photo from {message.from_user.full_name}")
            photo: types.PhotoSize = message.photo[-1]
            url = await _process_photo(photo, tg_bot)
            user_text = f"{user_text} {url}"
    elif message.content_type == enums.ContentType.VOICE and message.voice:
        if SETTINGS.VOICE_PROCESSOR is not None:
            logging.debug(f"processing voice from {message.from_user.full_name}")
            voice: types.Voice = message.voice
            user_text = await _process_voice(voice, tg_bot=tg_bot)
    elif message.content_type == enums.ContentType.DOCUMENT and message.document:
        logging.debug(f"processing document from {message.from_user.full_name}")
        document = message.document
        file_path = await _process_document(document, tg_bot)
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


async def _process_voice(voice: types.Voice, tg_bot: AIOGramBot):
    client = AsyncOpenAI(base_url=SETTINGS.VOICE_OPENAI_API_BASE_URL,
                         api_key=SETTINGS.VOICE_OPENAI_API_KEY)
    audio_client: AsyncTranscriptions = AsyncTranscriptions(client=client)

    file: types.File = await tg_bot.get_file(voice.file_id)
    file_path = file.file_path
    local_file_path = f"{SETTINGS.VOICE_FILE_LOCATION}/{file.file_unique_id}.ogg"
    await tg_bot.download_file(file_path, local_file_path)

    # converted_to_feasible_file = convert_ogg_audio(local_file_path)
    with open(local_file_path, "rb") as converted_to_feasible_file:
        transcription = await audio_client.create(language="ru", model=SETTINGS.VOICE_OPENAI_API_MODEL,
                                                  file=converted_to_feasible_file,
                                                  response_format="text")
    if hasattr(transcription, 'text'):
        return transcription.text
    else:
        return transcription


async def _process_document(document: types.Document, tg_bot: AIOGramBot):
    file: types.File = await tg_bot.get_file(document.file_id)
    file_path = file.file_path
    photo_file: BinaryIO = await tg_bot.download_file(file_path)
    file_path = photo_file.file_path
    return file_path
