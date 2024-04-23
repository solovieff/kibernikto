import logging
import os
from typing import BinaryIO, Literal

from aiogram import types, enums, Bot as AIOGramBot
from openai import AsyncOpenAI
from openai.resources.audio import AsyncTranscriptions
from pydantic_settings import BaseSettings

from kibernikto.utils.image import publish_image_file
from . import _gladia


class PreprocessorSettings(BaseSettings):
    VOICE_PROCESSOR: Literal["openai", "gladia", "auto"] | None = None
    IMAGE_SUMMARIZATION_OPENAI_API_KEY: str | None = None
    VOICE_OPENAI_API_KEY: str | None = None
    VOICE_OPENAI_API_MODEL: str = "whisper-1"
    VOICE_OPENAI_API_BASE_URL: str | None = None
    VOICE_FILE_LOCATION: str = "/tmp"
    PRE_FILE_LOCATION: str = "/tmp"
    VOICE_GLADIA_API_KEY: str | None = None
    VOICE_GLADIA_MIN_SIZE_BYTES: int = 1_000_000
    VOICE_GLADIA_CONTEXT: str | None = None


SETTINGS = PreprocessorSettings()


async def get_message_text(message: types.Message, tg_bot: AIOGramBot):
    """
    returns text to be processed by AI and it's plugins

    :param message:
    :param tg_bot:
    :return:
    """
    user_text = message.md_text
    files = None

    who = f"{message.from_user.username}:{message.from_user.id}"
    logging.debug(f"processing {message.content_type} from {who}")
    if message.content_type == enums.ContentType.PHOTO and message.photo:
        if SETTINGS.IMAGE_SUMMARIZATION_OPENAI_API_KEY is not None:
            photo: types.PhotoSize = message.photo[-1]
            url = await _process_photo(photo, tg_bot)
            user_text = f"{user_text} {url}"
    elif message.content_type == enums.ContentType.VOICE and message.voice:
        if SETTINGS.VOICE_PROCESSOR is not None:
            voice: types.Voice = message.voice
            user_text = await _process_voice(voice, tg_bot=tg_bot)
        else:
            pass
    elif message.content_type == enums.ContentType.DOCUMENT and message.document:
        logging.debug(f"processing document from {who}")
        document = message.document
        file_path = await _process_document(document, tg_bot)
    elif message.content_type == enums.ContentType.TEXT and message.text:
        logging.debug(f"processing text from {who}")
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


async def _process_voice(voice: types.Voice, tg_bot: AIOGramBot, user_text: str = "", delayed_callback = None):
    file: types.File = await tg_bot.get_file(voice.file_id)
    file_path = file.file_path
    local_file_path = f"{SETTINGS.VOICE_FILE_LOCATION}/{file.file_unique_id}.ogg"
    await tg_bot.download_file(file_path, local_file_path)

    resulting_text = None
    file_is_big = os.path.getsize(local_file_path) > SETTINGS.VOICE_GLADIA_MIN_SIZE_BYTES

    logging.info(f"processing big file: {local_file_path}")

    if SETTINGS.VOICE_PROCESSOR == "openai":
        resulting_text = await _process_voice_openai(local_file_path)
    elif SETTINGS.VOICE_PROCESSOR == "gladia":
        await _process_voice_gladia(local_file_path=local_file_path,
                                    user_message=user_text,
                                    call_on_finish=None,
                                    is_user_request=not file_is_big,
                                    )
    elif SETTINGS.VOICE_PROCESSOR == "auto":
        if file_is_big and SETTINGS.VOICE_GLADIA_API_KEY is not None:
            await _process_voice_gladia(local_file_path=local_file_path,
                                        user_message=user_text,
                                        call_on_finish=delayed_callback,
                                        is_user_request=False,
                                        )
        else:
            resulting_text = await _process_voice_openai(local_file_path)
    return resulting_text


async def _process_voice_openai(local_file_path):
    """
    Process voice using OpenAI API.

    :param local_file_path: Path to the local file.
    :type local_file_path: str
    :return: Transcription text or the transcription object.
    :rtype: tuple(str or object, None)
    """
    client = AsyncOpenAI(base_url=SETTINGS.VOICE_OPENAI_API_BASE_URL,
                         api_key=SETTINGS.VOICE_OPENAI_API_KEY)
    audio_client: AsyncTranscriptions = AsyncTranscriptions(client=client)

    # not converted actually :)
    with open(local_file_path, "rb") as converted_to_feasible_file:
        transcription = await audio_client.create(model=SETTINGS.VOICE_OPENAI_API_MODEL,
                                                  file=converted_to_feasible_file,
                                                  response_format="text")
    if hasattr(transcription, 'text'):
        return transcription.text
    else:
        return transcription


async def _process_voice_gladia(local_file_path, user_message, call_on_finish, is_user_request=False):
    """
    :param local_file_path: The local file path of the voice input file.
    :type local_file_path: str
    :param user_message: The user's message corresponding to the voice input.
    :type user_message: str
    :param call_on_finish: The callback function to be called when processing finishes.
    :type call_on_finish: callable
    :param is_user_request: Optional parameter to indicate if the voice input is a user request and should not be processed as dialogue or summarized. Defaults to False.
    :type is_user_request: bool
    :return: None
    :rtype: None

    This method processes the voice input using Gladia's audio processing functionality. It takes the local file path of the voice input file, the user's message, the callback function to
    * be called when processing finishes, and an optional parameter to indicate if the voice input is a user request. The default value for is_user_request is False.

    Example usage:
        await _process_voice_gladia('/path/to/voice/input.wav', 'Hello', callback_func, True)
    """
    await _gladia.process_audio(file_path=local_file_path, callback=call_on_finish, user_message=user_message,
                                context_prompt=SETTINGS.VOICE_GLADIA_CONTEXT, basic=is_user_request)
    return None


async def _process_document(document: types.Document, tg_bot: AIOGramBot):
    file: types.File = await tg_bot.get_file(document.file_id)
    file_path = file.file_path
    photo_file: BinaryIO = await tg_bot.download_file(file_path)
    file_path = photo_file.file_path
    return file_path
