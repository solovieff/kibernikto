import logging
import os
from typing import Literal

from aiogram import types, enums, Bot as AIOGramBot
from aiogram.enums import MessageOriginType
from aiogram.exceptions import TelegramBadRequest
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.storage.singletons import tg_media_store as media_store
from kibernikto.utils.image_hosting import image_hosting
from kibernikto.telegram.utils import permissions

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

# Media attributes shared by Message and ExternalReplyInfo, described as cheap text markers.
_MEDIA_KINDS = ("photo", "video", "video_note", "animation", "voice", "audio", "document",
                "sticker", "story", "poll", "location", "venue", "contact", "dice")


class TelegramMessagePreprocessor:

    async def process_tg_message(self, message: types.Message) -> list[UserContent] | None:
        if message.content_type in IGNORED_TYPES:
            await message.reply("Unknown message type :(")
            return None

        user = message.from_user
        logging.debug("processing %s from %s", message.content_type,
                      f"{user.username}:{user.id}" if user else "unknown")

        own: list[UserContent] = []
        own.extend(self._process_caption(message))
        own.extend(await self._process_photo(message))
        own.extend(await self._process_voice(message))
        own.extend(await self._process_document(message))
        own.extend(self._process_text(message))

        parts = [*await self._process_reply(message), *self._process_forward(message, own)]
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
            # Durable local copy so agents can read the original later; its ref is kept on the ImageUrl.
            media_ref = None
            try:
                photo_bytes = photo_file.getvalue() if hasattr(photo_file, "getvalue") else photo_file
                ext = os.path.splitext(file.file_path)[1] or ".jpg"
                media_ref = await media_store.save(str(message.chat.id), photo_bytes, ext=ext,
                                                   name=f"{photo.file_unique_id}{ext}")
            except Exception as exc:
                logging.error("Error saving photo to media store: %s", exc)
            url = await image_hosting.publish(photo_file.getvalue() if hasattr(photo_file, "getvalue") else photo_file, photo.file_unique_id)
            if not url:
                return ["[Image processing: failed to publish image]"]
            logging.info("published image: %s", url)
            metadata = {"media_ref": media_ref, "media_store": "telegram"} if media_ref else None
            return [ImageUrl(url=url, vendor_metadata=metadata)]
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
            local_path = media_store.tmp_path(f"{file.file_unique_id}{ext}")
            await message.bot.download_file(file.file_path, str(local_path))
        except Exception as exc:
            logging.error("Error downloading voice file: %s", exc)
            return [f"[Voice transcription error: failed to download — {exc}]"]

        try:
            transcription = await self._transcribe_openai(str(local_path))
        except Exception as exc:
            logging.error("Error transcribing voice: %s", exc)
            return [f"[Voice transcription error: {exc}]"]
        finally:
            media_store.cleanup_tmp(local_path)

        if not transcription:
            return ["[Voice transcription error: empty result]"]

        return [f"[Voice transcription]: {transcription}"]

    async def _process_reply(self, message: types.Message) -> list[UserContent]:
        quote = message.quote.text if message.quote else None
        if (reply := message.reply_to_message) and not reply.forum_topic_created:
            author = _sender_label(reply, message.bot.id if message.bot else None)
            # The bot already sees its own messages in history; only an explicit fragment adds signal.
            body = [quote] if quote else [] if author == _SELF else await self._quoted_body(reply)
        elif external := message.external_reply:
            author = f"{_origin_label(external.origin)} in another chat"
            body = [quote] if quote else _media_markers(external)
        elif story := message.reply_to_story:
            return [f"[Replying to a story from {_chat_label(story.chat)}]"]
        else:
            return []

        header = f"[Replying to {author}'s message{', quoted fragment' if quote else ''}]"
        return [f"{header}:", *body, "[End of quoted message]"] if body else [header]

    async def _quoted_body(self, reply: types.Message) -> list[UserContent]:
        # Text + republished photo only; no transcription, documents or replies to stickers.
        body: list[UserContent] = [*self._process_caption(reply), *self._process_text(reply)]
        body.extend(await self._process_photo(reply))
        body.extend(_media_markers(reply, skip=("photo",)))
        return body

    def _process_forward(self, message: types.Message, own: list[UserContent]) -> list[UserContent]:
        if not (origin := message.forward_origin):
            return own
        header = f"[Forwarded from {_origin_label(origin)}]"
        return [f"{header}:", *own, "[End of forwarded message]"] if own else [header]

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
            )

        # Default JSON format: every OpenAI-compatible gateway (routerai, ...) returns `.text`.
        return transcription.text


_SELF = "bot (you)"


def _user_label(user: types.User) -> str:
    return f"@{user.username}" if user.username else user.full_name


def _chat_label(chat: types.Chat) -> str:
    return f"@{chat.username}" if chat.username else chat.title or chat.full_name or str(chat.id)


def _sender_label(message: types.Message, bot_id: int | None) -> str:
    # sender_chat wins: anonymous admins and channel posts carry a placeholder from_user.
    if message.sender_chat:
        label = _chat_label(message.sender_chat)
    elif message.from_user:
        label = _SELF if message.from_user.id == bot_id else _user_label(message.from_user)
    else:
        label = "unknown"
    return f"{label}, forwarded from {_origin_label(message.forward_origin)}" if message.forward_origin else label


def _origin_label(origin: types.MessageOrigin) -> str:
    match origin.type:
        case MessageOriginType.USER:
            return _user_label(origin.sender_user)
        case MessageOriginType.CHAT:
            return _chat_label(origin.sender_chat)
        case MessageOriginType.CHANNEL:
            return f"{_chat_label(origin.chat)} (message #{origin.message_id})"
        case MessageOriginType.HIDDEN_USER:
            return origin.sender_user_name
        case _:
            return "unknown"


def _media_markers(source: types.Message | types.ExternalReplyInfo, skip: tuple[str, ...] = ()) -> list[UserContent]:
    return [f"[{kind.replace('_', ' ')}]" for kind in _MEDIA_KINDS
            if kind not in skip and getattr(source, kind, None)]


async def _reply_async(text: str, message: types.Message, tg_bot: AIOGramBot) -> None:
    await tg_bot.send_chat_action(message.chat.id, "typing")
    await message.reply(text)
