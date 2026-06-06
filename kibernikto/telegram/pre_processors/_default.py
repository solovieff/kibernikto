import logging
import os
from typing import Literal

from aiogram import types, enums, Bot as AIOGramBot
from aiogram.enums import MessageOriginType
from aiogram.exceptions import TelegramBadRequest
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.utils.image import publish_image_file
from kibernikto.telegram.utils import permissions
from kibernikto.telegram.config import TELEGRAM_SETTINGS

from pydantic_ai.messages import ImageUrl, UserContent


class PreprocessorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRANSCRIBE_")

    PROCESSOR: Literal["openai", "elevenlabs", "auto"] | None = None
    OPENAI_API_KEY: str | None = None
    OPENAI_API_MODEL: str = "whisper-1"
    OPENAI_API_BASE_URL: str | None = None
    OPENAI_API_LANGUAGE: str | None = "ru"
    MIN_COMPLEX_SECONDS: int = 300


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

_MAX_REPLY_DEPTH = 3  # prevent recursion on deeply nested reply chains


class TelegramMessagePreprocessor:

    async def process_tg_message(
            self,
            message: types.Message,
            *,
            _reply_depth: int = 0,
    ) -> list[UserContent] | None:
        if message.content_type in IGNORED_TYPES:
            await message.reply("Unknown message type :(")
            return None

        who = f"{message.from_user.username}:{message.from_user.id}"
        logging.debug("processing %s from %s", message.content_type, who)

        parts: list[UserContent] = []
        parts.extend(self._process_caption(message))
        parts.extend(await self._process_reply(message, _reply_depth=_reply_depth))
        parts.extend(await self._process_photo(message))
        parts.extend(self._process_forward(message))
        parts.extend(await self._process_voice(message))
        parts.extend(await self._process_document(message))
        parts.extend(self._process_text(message))

        return parts or None

    # ── Per-content-type handlers (each returns list[UserContent]) ──────────────

    def _process_caption(self, message: types.Message) -> list[UserContent]:
        return [message.caption] if message.caption else []

    def _process_text(self, message: types.Message) -> list[UserContent]:
        return [message.text] if message.text else []

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
            logging.info("published image: %s", url)
            return [ImageUrl(url=url)]
        except Exception as exc:
            logging.error("Error processing photo: %s", exc)
            return [f"[Image processing error: {exc}]"]

    async def _process_voice(self, message: types.Message) -> list[UserContent]:
        if not message.voice and not message.audio:
            return []

        if not SETTINGS.OPENAI_API_KEY:
            return ["[Voice transcription error: no TRANSCRIBE_OPENAI_API_KEY configured]"]

        voice = message.voice or message.audio

        try:
            file = await message.bot.get_file(voice.file_id)
        except TelegramBadRequest as exc:
            logging.error("Telegram error getting voice file: %s", exc)
            return [f"[Voice transcription error: Telegram rejected file request — {exc}]"]

        try:
            file_name = os.path.basename(file.file_path)
            ext = os.path.splitext(file_name)[1]
            local_path = f"{TELEGRAM_SETTINGS.FILES_LOCATION}/{file.file_unique_id}{ext}"
            await message.bot.download_file(file.file_path, local_path)
        except Exception as exc:
            logging.error("Error downloading voice file: %s", exc)
            return [f"[Voice transcription error: failed to download — {exc}]"]

        try:
            transcription = await self._transcribe_openai(local_path)
        except Exception as exc:
            logging.error("Error transcribing audio: %s", exc)
            return [f"[Voice transcription error: {exc}]"]

        if not transcription:
            return ["[Voice transcription error: empty result]"]

        return [f"[Voice transcription]: {transcription}"]

    async def _process_reply(
            self,
            message: types.Message,
            *,
            _reply_depth: int = 0,
    ) -> list[UserContent]:
        reply = message.reply_to_message
        if not reply:
            return []

        # Identify the quoted message author.
        if reply.from_user:
            if reply.from_user.id == (await message.bot.me()).id:
                author = "bot (you)"
            elif reply.from_user.username:
                author = f"@{reply.from_user.username}"
            else:
                author = reply.from_user.full_name
        else:
            author = "unknown"

        # Recurse only up to _MAX_REPLY_DEPTH to avoid stack overflow on deep chains.
        if _reply_depth >= _MAX_REPLY_DEPTH:
            return [f"[Replying to {author}'s message — further nesting truncated]"]

        quoted_parts = await self.process_tg_message(reply, _reply_depth=_reply_depth + 1)
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
                source = f"{chat.title or chat.id} (message #{origin.message_id})"
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
            return [f"[Document error: unsupported type {document.mime_type!r}, only PDF is supported]"]

        # TODO: implement real PDF extraction (e.g. pypdf / pdfminer).
        return [f"[Document error: PDF processing not yet implemented for {document.file_name!r}]"]

    async def _transcribe_openai(self, local_file_path: str) -> str:
        from openai import AsyncOpenAI
        from openai.resources.audio import AsyncTranscriptions

        client = AsyncOpenAI(
            base_url=SETTINGS.OPENAI_API_BASE_URL,
            api_key=SETTINGS.OPENAI_API_KEY,
        )
        audio_client = AsyncTranscriptions(client=client)

        with open(local_file_path, "rb") as audio_file:
            transcription = await audio_client.create(
                model=SETTINGS.OPENAI_API_MODEL,
                language=SETTINGS.OPENAI_API_LANGUAGE,
                file=audio_file,
                response_format="text",
            )

        return transcription.text if hasattr(transcription, "text") else transcription


async def _reply_async(text: str, message: types.Message, tg_bot: AIOGramBot) -> None:
    await tg_bot.send_chat_action(message.chat.id, "typing")
    await message.reply(text)
