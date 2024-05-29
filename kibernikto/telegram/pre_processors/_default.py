import logging
import os
import pprint
from typing import BinaryIO, Literal, Callable

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
    VOICE_MIN_COMPLEX_SECONDS: int = 300  # more than 5 minutes seems to be a dialogue or smth.
    VOICE_GLADIA_CONTEXT: str | None = None


SETTINGS = PreprocessorSettings()


class TelegramMessagePreprocessor():
    async def process_tg_message(self, message: types.Message, tg_bot: AIOGramBot) -> str:
        """
        returns text to be processed by AI and it's plugins

        :param message:
        :param tg_bot:
        :return:
        """
        user_text = message.md_text
        file_info = None

        who = f"{message.from_user.username}:{message.from_user.id}"
        logging.debug(f"processing {message.content_type} from {who}")
        if message.content_type == enums.ContentType.PHOTO and message.photo:
            if SETTINGS.IMAGE_SUMMARIZATION_OPENAI_API_KEY is not None:
                photo: types.PhotoSize = message.photo[-1]
                url = await self._process_photo(photo, tg_bot, message=message)
                user_text = f"{user_text} {url}"
        elif message.content_type == enums.ContentType.VOICE and message.voice:
            if SETTINGS.VOICE_PROCESSOR is not None:
                voice: types.Voice = message.voice
                user_text, file_info = await self._process_voice(voice, tg_bot=tg_bot, message=message)
                pprint.pprint(file_info)
                # await message.reply()
            else:
                logging.warning(f"No voice processor configured for {message.voice.file_id}")
        elif message.content_type == enums.ContentType.DOCUMENT and message.document:
            logging.debug(f"processing document from {who}")
            document = message.document
            user_text = await self._process_document(document, tg_bot, message)
        elif message.content_type == enums.ContentType.TEXT and message.text:
            logging.debug(f"processing text from {who}")
            user_text = await self._process_text(message)
        return user_text

    async def _process_text(self, message: types.Message):
        return message.text

    async def _process_photo(self, photo: types.PhotoSize, tg_bot: AIOGramBot, message: types.Message = None):
        file: types.File = await tg_bot.get_file(photo.file_id)
        file_path = file.file_path
        photo_file: BinaryIO = await tg_bot.download_file(file_path)
        # file_path = photo_file.file_path
        url = await publish_image_file(photo_file, photo.file_unique_id)
        logging.info(f"published image: {url}")
        return url

    async def _process_voice(self, voice: types.Voice, tg_bot: AIOGramBot, user_text: str = "",
                             message: types.Message = None):
        """
        :param voice: The `types.Voice` object containing the voice file information.
        :type voice: `types.Voice`
        :param tg_bot: The `AIOGramBot` instance
        :type tg_bot: `AIOGramBot`
        :param user_text: The optional text accompanying the voice message.
        :type user_text: `str`
        :param delayed_callback: The optional callback function to be called after processing the voice message.
        :type delayed_callback: `Callable`
        :return: The resulting text after processing the voice message.
        :rtype: `str`
        """
        file: types.File = await tg_bot.get_file(voice.file_id)
        file_path = file.file_path

        local_file_path = f"{SETTINGS.VOICE_FILE_LOCATION}/{file.file_unique_id}.ogg"
        await tg_bot.download_file(file_path, local_file_path)

        resulting_text = None
        file_info = None

        comlex_analysis = voice.duration > SETTINGS.VOICE_MIN_COMPLEX_SECONDS

        logging.info(f"Is {local_file_path} big and does it need comlex_analysis? {comlex_analysis}!")

        if SETTINGS.VOICE_PROCESSOR == "openai":
            resulting_text = await self._process_voice_openai(local_file_path)
        elif SETTINGS.VOICE_PROCESSOR == "gladia":
            resulting_text, file_info = await self._process_voice_gladia(local_file_path=local_file_path,
                                                                         user_message=user_text,
                                                                         comlex_analysis=comlex_analysis,
                                                                         )
        elif SETTINGS.VOICE_PROCESSOR == "auto":
            if comlex_analysis is True and SETTINGS.VOICE_GLADIA_API_KEY is not None:
                resulting_text, file_info = await self._process_voice_gladia(local_file_path=local_file_path,
                                                                             user_message=user_text,
                                                                             comlex_analysis=comlex_analysis,
                                                                             )
            else:
                resulting_text = await self._process_voice_openai(local_file_path)
        return resulting_text, file_info

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

    async def _process_voice_gladia(self, local_file_path, user_message, comlex_analysis=False):
        """
        :param local_file_path: The local file path of the voice input file.
        :type local_file_path: str
        :param user_message: The user's message corresponding to the voice input.
        :type user_message: str
        :param comlex_analysis: Optional parameter to indicate if the voice input is a user request and should not be processed as dialogue or summarized. Defaults to False.
        :type comlex_analysis: bool
        :return: None
        :rtype: None

        This method processes the voice input using Gladia's audio processing functionality. It takes the local file path of the voice input file, the user's message,
        * The default value for comlex_analysis is False.

        Example usage:
            await _process_voice_gladia('/path/to/voice/input.wav', 'Hello', True)
        """
        return await _gladia.process_audio(file_path=local_file_path, user_message=user_message,
                                           context_prompt=SETTINGS.VOICE_GLADIA_CONTEXT, basic=not comlex_analysis)

    async def _process_document(self, document: types.Document, tg_bot: AIOGramBot, message: types.Message):
        file: types.File = await tg_bot.get_file(document.file_id)
        file_path = file.file_path
        photo_file: BinaryIO = await tg_bot.download_file(file_path)
        file_path = photo_file.file_path
        return file_path
