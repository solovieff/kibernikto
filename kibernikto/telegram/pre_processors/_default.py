import logging
import os
from typing import BinaryIO, Literal, Sequence

from aiogram import types, enums, Bot as AIOGramBot
from aiogram.enums import MessageOriginType
from aiogram.exceptions import TelegramBadRequest
from pydantic_settings import BaseSettings

from kibernikto.utils.image import publish_image_file
from kibernikto.telegram.utils import permissions
from kibernikto.telegram.config import TELEGRAM_SETTINGS


class PreprocessorSettings(BaseSettings):
    TRANSCRIBE_PROCESSOR: Literal["openai", "elevenlabs", "auto"] | None = None
    TRANSCRIBE_OPENAI_API_KEY: str | None = None
    TRANSCRIBE_OPENAI_API_MODEL: str = "whisper-1"
    TRANSCRIBE_OPENAI_API_BASE_URL: str | None = None
    TRANSCRIBE_OPENAI_API_LANGUAGE: str | None = "ru"
    TRANSCRIBE_MIN_COMPLEX_SECONDS: int = 300


SETTINGS = PreprocessorSettings()

IGNORED_TYPES = {
    enums.ContentType.STICKER,
    enums.ContentType.NEW_CHAT_MEMBERS,
    enums.ContentType.LEFT_CHAT_MEMBER,
    enums.ContentType.NEW_CHAT_TITLE,
    enums.ContentType.NEW_CHAT_PHOTO,
    enums.ContentType.DELETE_CHAT_PHOTO,
    enums.ContentType.GROUP_CHAT_CREATED,
    enums.ContentType.SUPERGROUP_CHAT_CREATED,
    enums.ContentType.CHANNEL_CHAT_CREATED,
    enums.ContentType.MESSAGE_AUTO_DELETE_TIMER_CHANGED,
    enums.ContentType.VIDEO_CHAT_SCHEDULED,
    enums.ContentType.VIDEO_CHAT_STARTED,
    enums.ContentType.VIDEO_CHAT_ENDED,
    enums.ContentType.VIDEO_CHAT_PARTICIPANTS_INVITED,
    enums.ContentType.PROXIMITY_ALERT_TRIGGERED,
    enums.ContentType.WEB_APP_DATA,
}

from pydantic_ai.messages import ImageUrl, AudioUrl, UserContent


class TelegramMessagePreprocessor:

    async def process_tg_message(self, message: types.Message) -> list[UserContent] | None:
        if message.content_type in IGNORED_TYPES:
            await message.reply("Unknown message type :(")
            return None

        who = f"{message.from_user.username}:{message.from_user.id}"
        logging.debug(f"processing {message.content_type} from {who}")

        parts: list[UserContent] = []
        parts.extend(self._process_caption(message))
        parts.extend(await self._process_reply(message))
        parts.extend(await self._process_photo(message))
        parts.extend(self._process_forward(message))
        parts.extend(await self._process_voice(message))
        parts.extend(await self._process_document(message))
        parts.extend(self._process_text(message))

        if not parts:
            return None

        return parts

    # ──────────────────────────────────────
    #  Каждый возвращает list[UserContent]
    # ──────────────────────────────────────

    def _process_caption(self, message: types.Message) -> list[UserContent]:
        if not message.caption:
            return []
        return [message.caption]

    def _process_text(self, message: types.Message) -> list[UserContent]:
        if not message.text:
            return []
        return [message.text]

    async def _process_photo(self, message: types.Message) -> list[UserContent]:
        if not message.photo:
            return []

        try:
            photo = message.photo[-1]
            file = await message.bot.get_file(photo.file_id)
            photo_file = await message.bot.download_file(file.file_path)
            url = await publish_image_file(photo_file, photo.file_unique_id)
            if not url:
                return ["[Image processing: failed to publish image]"]

            logging.info(f"published image: {url}")
            return [ImageUrl(url=url)]
        except Exception as e:
            logging.error(f"Error processing photo: {e}")
            return [f"[Image processing error: {e}]"]

    async def _process_voice(self, message: types.Message) -> list[UserContent]:
        if not message.voice and not message.audio:
            return []

        if not SETTINGS.TRANSCRIBE_OPENAI_API_KEY:
            return ["[Voice transcription error: no TRANSCRIBE_OPENAI_API_KEY configured]"]

        voice = message.voice or message.audio

        try:
            file = await message.bot.get_file(voice.file_id)
        except TelegramBadRequest as e:
            logging.error(f"Telegram error getting voice file: {e}")
            return [f"[Voice transcription error: Telegram rejected file request — {e}]"]

        try:
            file_name = os.path.basename(file.file_path)
            file_extension = os.path.splitext(file_name)[1]
            local_file_path = f"{TELEGRAM_SETTINGS.FILES_LOCATION}/{file.file_unique_id}{file_extension}"
            await message.bot.download_file(file.file_path, local_file_path)
        except Exception as e:
            logging.error(f"Error downloading voice file: {e}")
            return [f"[Voice transcription error: failed to download — {e}]"]

        try:
            transcription = await self._transcribe_openai(local_file_path)
        except Exception as e:
            logging.error(f"Error transcribing audio: {e}")
            return [f"[Voice transcription error: {e}]"]

        if not transcription:
            return ["[Voice transcription error: empty result]"]

        return [f"[Voice transcription]: {transcription}"]

    async def _process_reply(self, message: types.Message) -> list[UserContent]:
        reply = message.reply_to_message
        if not reply:
            return []

        # кто автор цитируемого сообщения
        if reply.from_user:
            if reply.from_user.id == (await message.bot.me()).id:
                author = "bot (you)"
            elif reply.from_user.username:
                author = f"@{reply.from_user.username}"
            else:
                author = reply.from_user.full_name
        else:
            author = "unknown"

        # рекурсивно обрабатываем цитируемое сообщение
        quoted_parts = await self.process_tg_message(reply)

        if not quoted_parts:
            return [f"[Replying to {author}'s message]"]

        return [
            f"[Replying to {author}'s message]:",
            *quoted_parts,
            "[End of quoted message]",
        ]

    def _process_forward(self, message: types.Message) -> list[UserContent]:
        origin = message.forward_origin
        if not origin:
            return []

        match origin.type:
            case MessageOriginType.USER:
                user = origin.sender_user
                source = f"@{user.username}" if user.username else user.full_name
            case MessageOriginType.CHAT:
                source = origin.sender_chat.title or str(origin.sender_chat.id)
            case MessageOriginType.CHANNEL:
                chat = origin.chat
                msg_id = origin.message_id
                source = f"{chat.title or chat.id} (message #{msg_id})"
            case MessageOriginType.HIDDEN_USER:
                source = origin.sender_user_name
            case _:
                source = "unknown"

        return [f"[Forwarded from {source}]:"]

    async def _process_document(self, message: types.Message) -> list[UserContent]:
        if not message.document:
            return []

        if not permissions.is_from_admin(message):
            return ["[Document error: only admin can upload files]"]

        document = message.document

        if document.mime_type != "application/pdf":
            return [f"[Document error: unsupported type {document.mime_type}, only PDF is supported]"]

        try:
            file = await message.bot.get_file(document.file_id)
            binary_data = await message.bot.download_file(file.file_path)

            await _reply_async(text=f"Loading {document.file_name}", tg_bot=message.bot, message=message)

            local_file_path = os.path.join(TELEGRAM_SETTINGS.FILES_LOCATION, document.file_name)
            with open(local_file_path, "wb") as f:
                f.write(binary_data.getvalue())

            # TODO: реальная обработка PDF
            return [f"[Document error: PDF processing not implemented yet for {document.file_name}]"]
        except Exception as e:
            logging.error(f"Error processing document from user {message.from_user.id}: {e}")
            return [f"[Document processing error: {e}]"]

    async def _transcribe_openai(self, local_file_path: str) -> str:
        from openai import AsyncOpenAI
        from openai.resources.audio import AsyncTranscriptions

        client = AsyncOpenAI(
            base_url=SETTINGS.TRANSCRIBE_OPENAI_API_BASE_URL,
            api_key=SETTINGS.TRANSCRIBE_OPENAI_API_KEY,
        )
        audio_client = AsyncTranscriptions(client=client)

        with open(local_file_path, "rb") as audio_file:
            transcription = await audio_client.create(
                model=SETTINGS.TRANSCRIBE_OPENAI_API_MODEL,
                language=SETTINGS.TRANSCRIBE_OPENAI_API_LANGUAGE,
                file=audio_file,
                response_format="text",
            )

        if hasattr(transcription, "text"):
            return transcription.text
        return transcription


async def _reply_async(text: str, message: types.Message, tg_bot: AIOGramBot):
    await tg_bot.send_chat_action(message.chat.id, "typing")
    await message.reply(text)
