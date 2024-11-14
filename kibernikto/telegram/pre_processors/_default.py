import json
import logging
import os
import pprint
from typing import BinaryIO, Literal, Callable

import aiofiles
from aiogram import types, enums, Bot as AIOGramBot
from aiogram.types import FSInputFile
from openai import AsyncOpenAI
from openai.resources.audio import AsyncTranscriptions
from pydantic_settings import BaseSettings

from kibernikto.utils.image import publish_image_file
from . import _gladia
from kibernikto.utils import permissions


class PreprocessorSettings(BaseSettings):
    TG_MASTER_ID: int
    TG_MASTER_IDS: list = []
    TG_PUBLIC: bool = False
    VOICE_PROCESSOR: Literal["openai", "gladia", "auto"] | None = None
    IMAGE_SUMMARIZATION_OPENAI_API_KEY: str | None = None
    VOICE_OPENAI_API_KEY: str | None = None
    VOICE_OPENAI_API_MODEL: str = "whisper-1"
    VOICE_OPENAI_API_BASE_URL: str | None = None
    VOICE_OPENAI_API_LANGUAGE: str | None = 'ru'
    VOICE_FILE_LOCATION: str = "/tmp"
    TG_FILES_LOCATION: str = "/tmp"
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
        user_text = message.caption if message.caption else message.md_text
        file_info = None

        who = f"{message.from_user.username}:{message.from_user.id}"
        logging.debug(f"processing {message.content_type} from {who}")

        if message.content_type == enums.ContentType.PHOTO and message.photo:
            if SETTINGS.IMAGE_SUMMARIZATION_OPENAI_API_KEY is not None:
                photo: types.PhotoSize = message.photo[-1]
                url = await self._process_photo(photo, tg_bot, message=message)
                user_text = f"{user_text} {url}"
            return user_text

        elif message.content_type == enums.ContentType.VOICE and message.voice is not None:
            if SETTINGS.VOICE_PROCESSOR is not None:
                voice: types.Voice = message.voice
                resulting_text, file_info = await self._process_voice(voice, tg_bot=tg_bot, user_text=user_text, message=message)
                pprint.pprint(file_info)

                if user_text:  # If the text is attached. Most likely this option can only happen in theory.
                    if resulting_text and file_info and "dialogue_location" in file_info:
                        summary = FSInputFile(file_info['dialogue_location'], filename="everything.txt")
                        await message.reply_document(document=summary, caption=resulting_text)
                        return None
                else:

                    if file_info and "dialogue_location" in file_info:
                        summary = FSInputFile(file_info['dialogue_location'], filename="everything.txt")
                        await message.reply_document(document=summary, caption=file_info['summarization'])
                        return None
            else:
                logging.warning(f"No voice processor configured for {message.voice.file_id}")
                return None
        
        elif message.content_type == enums.ContentType.AUDIO and message.audio:
            if SETTINGS.VOICE_PROCESSOR is not None:
                voice: types.Audio = message.audio
                resulting_text, file_info = await self._process_voice(voice, tg_bot=tg_bot, user_text=user_text, message=message)
                pprint.pprint(file_info)

                if user_text:
                    if resulting_text and file_info and "dialogue_location" in file_info:
                        summary = FSInputFile(file_info['dialogue_location'], filename="everything.txt")
                        await message.reply_document(document=summary, caption=resulting_text)
                        return None
                else:
                    if file_info and "dialogue_location" in file_info:
                        summary = FSInputFile(file_info['dialogue_location'], filename="everything.txt")
                        await message.reply_document(document=summary, caption=file_info['summarization'])
                        return None
            else:
                logging.warning(f"No voice processor configured for {message.voice.file_id}")
                return None

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
        file_name = os.path.basename(file_path)
        file_extension = os.path.splitext(file_name)[1]

        local_file_path = f"{SETTINGS.VOICE_FILE_LOCATION}/{file.file_unique_id}{file_extension}"

        await tg_bot.download_file(file_path, local_file_path)

        resulting_text = None
        file_info = None

        complex_analysis = voice.duration > SETTINGS.VOICE_MIN_COMPLEX_SECONDS

        if complex_analysis and not permissions.is_from_admin(message):
            await message.answer("⏳complex_analysis disabled for non-admin users")
            return None, None
        elif complex_analysis:
            await message.answer(f"⏳performing complex_analysis for {voice.duration} second audio")
        logging.info(f"Is {local_file_path} big and does it need complex_analysis? {complex_analysis}!")

        if SETTINGS.VOICE_PROCESSOR == "openai":
            try:
                resulting_text = await self._process_voice_openai(local_file_path)
            except Exception as e:
                logging.error(f"Error while processing voice with OpenAI: {e}")
                await message.reply("An error occurred during voice processing with OpenAI")
                return None, None
        
        
        elif SETTINGS.VOICE_PROCESSOR == "gladia":
            try:
                resulting_text, file_info = await self._process_voice_gladia(local_file_path=local_file_path,
                                                                         user_message=user_text,
                                                                         complex_analysis=complex_analysis,
                                                                         )
                
                audio_to_llm = await extract_audio_to_llm(file_info)
                if audio_to_llm and audio_to_llm.get('success') and audio_to_llm.get('results'):
                    first_result = audio_to_llm['results'][0]
                    if first_result.get('success') and 'results' in first_result:
                        response_text = first_result['results'].get('response')
                        if response_text:
                            resulting_text = response_text

            except Exception as e:
                logging.error(f"Error while processing voice with Gladia: {e}")
                await message.reply("An error occurred during voice processing with Gladia.")
                return None, None   
            
        elif SETTINGS.VOICE_PROCESSOR == "auto":
            if complex_analysis is True and SETTINGS.VOICE_GLADIA_API_KEY is not None:
                try:
                    resulting_text, file_info = await self._process_voice_gladia(local_file_path=local_file_path,
                                                                             user_message=user_text,
                                                                             complex_analysis=complex_analysis,
                                                                             )
            
                    audio_to_llm = await extract_audio_to_llm(file_info)
                    if audio_to_llm and audio_to_llm.get('success') and audio_to_llm.get('results'):
                        first_result = audio_to_llm['results'][0]
                        if first_result.get('success') and 'results' in first_result:
                            response_text = first_result['results'].get('response')
                            if response_text:
                                resulting_text = response_text


                except Exception as e:
                    logging.error(f"Error while processing voice with Gladia: {e}")
                    await message.reply("An error occurred during voice processing with Gladia.")
                    return None, None
            
            else:
                try:
                    resulting_text = await self._process_voice_openai(local_file_path)
                except Exception as e:
                    logging.error(f"Error while processing voice with OpenAI: {e}")
                    await message.reply("An error occurred during voice processing with OpenAI.")
                    return None, None 

        return resulting_text, file_info

    async def _process_voice_openai(self, local_file_path):
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
                                                      language=SETTINGS.VOICE_OPENAI_API_LANGUAGE,
                                                      file=converted_to_feasible_file,
                                                      response_format="text")
        if hasattr(transcription, 'text'):
            return transcription.text
        else:
            return transcription

    async def _process_voice_gladia(self, local_file_path: str, user_message: str,
                                    complex_analysis: bool = False) -> object:
        """
        :param local_file_path: The local file path of the voice input file.
        :type local_file_path: str
        :param user_message: The user's message corresponding to the voice input.
        :type user_message: str
        :param complex_analysis: Optional parameter to indicate if the voice input is a user request and should not be processed as dialogue or summarized. Defaults to False.
        :type complex_analysis: bool
        :return: None
        :rtype: None

        This method processes the voice input using Gladia's audio processing functionality. It takes the local file path of the voice input file, the user's message,
        * The default value for complex_analysis is False.

        Example usage:
            await _process_voice_gladia('/path/to/voice/input.wav', 'Hello', True)
        """
        return await _gladia.process_audio(file_path=local_file_path, user_message=user_message,
                                           context_prompt=SETTINGS.VOICE_GLADIA_CONTEXT, basic=not complex_analysis)

    async def _process_document(self, document: types.Document, tg_bot: AIOGramBot, message: types.Message):
        if not permissions.is_from_admin(message):
            await message.reply(f"Только администратор может загружать файлы!")
            raise RuntimeError("Только администратор может загружать файлы!")

        file: types.File = await tg_bot.get_file(document.file_id)
        binary_data: BinaryIO = await tg_bot.download_file(file.file_path)

        if document.mime_type == 'application/pdf':
            message_text = f"Loading {document.file_name}"
            await reply_async(text=message_text, tg_bot=tg_bot, message=message)
            local_file_path = os.path.join(SETTINGS.TG_FILES_LOCATION, document.file_name)
            with open(local_file_path, 'wb') as f:
                f.write(binary_data.getvalue())
            try:
                await message.reply("Пока не знаю, что делать с вашим файлом, а так всё ок :(")
                return None
            except Exception as e:
                logging.error(f"Error processing PDF file from user {message.from_user.id}: {e}")
                await message.reply(f"Error loading file: {e}")
        else:
            await message.reply(f"Пока могу загружать только ПДФ!")
            raise RuntimeError("Пока могу загружать только ПДФ!")


async def reply_async(text: str, message: types.Message, tg_bot: AIOGramBot):
    await tg_bot.send_chat_action(message.chat.id, 'typing')
    await message.reply(text)


async def extract_audio_to_llm(file_info):
    """
    Extracts "audio_to_llm" section data from a JSON file whose path is specified in "full_location" of "file_info".

    :param file_info: A dictionary with file information containing the JSON file path in the full_location key.
    :return: The "audio_to_llm" data from the JSON file, or None if no data is found.
    """
    # print("Starting extract_audio_to_llm...")
    # print("Received file_info:", file_info)

    full_data_path = file_info.get('full_location')
    # print("full_data_path:", full_data_path)
    
    if not full_data_path:
        print("Path to file 'full_data.json' not found in file_info")
        return None

    if not os.path.exists(full_data_path):
        print(f"File {full_data_path} does not exist.")
        return None

    try:
        print(f"Attempting to open file at {full_data_path}")
        async with aiofiles.open(full_data_path, 'r') as f:
            content = await f.read()
            print("File content successfully read.")
            
            try:
                full_data = json.loads(content)
                print("JSON content successfully parsed.")
            except json.JSONDecodeError:
                print(f"Error: File {full_data_path} is not valid JSON.")
                return None

            # print("Parsed JSON data:", full_data)

            # Extract "audio_to_llm" section
            audio_to_llm = full_data.get('audio_to_llm')
            # print("audio_to_llm extracted:", audio_to_llm)
            
            if isinstance(audio_to_llm, dict):
                print("audio_to_llm data found and is a dictionary:", audio_to_llm)
                return audio_to_llm
            else:
                print("audio_to_llm data not found or not in expected format in full_data.json")
                return None

    except Exception as e:
        print(f"Unexpected error reading {full_data_path}: {e}")
        return None