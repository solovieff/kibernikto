# Telegram Preprocessing

`TelegramMessagePreprocessor` (`kibernikto/telegram/pre_processors/_default.py`) turns an aiogram
`Message` into a `list[UserContent]` that can be passed straight to `kibernikto_agent.run`. It is
the **only** place where Telegram-specific media handling lives.

## Public API

```python
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor

preprocessor = TelegramMessagePreprocessor()
parts: list[UserContent] | None = await preprocessor.process_tg_message(message)
```

- The class is **stateless** — every method is independent and there's no `__init__` state. The
  handlers call `TelegramMessagePreprocessor()` fresh on every message.
- Module-level `SETTINGS` and `IGNORED_TYPES` constants are loaded once at import.
- The return value is a `list[UserContent] | None`. `None` means "unknown / ignored content type" and
  is currently still passed to `kibernikto_agent.run(None, chat_id=...)`, which raises inside pydantic-ai
  — see [Common Gotchas](./../SKILL.md#common-gotchas) in the main SKILL.md.

## Top-level dispatch

```python
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
```

### Ignored content types

```python
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
```

A sticker reaching the preprocessor becomes "Unknown message type :(" + `None`. If you want stickers
to be handled (e.g. forwarded to the model as `ImageUrl`), remove `STICKER` from `IGNORED_TYPES` and
add a `_process_sticker` method.

## Per-content-type behaviour

### Text & caption

- `_process_caption(message)` → `[message.caption]` if present
- `_process_text(message)` → `[message.text]` if present

Both are first-class strings — pydantic-ai accepts `str` as a single `UserContent` and the agent
treats it as a user message.

### Photo

```python
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
        return [ImageUrl(url=url)]
    except Exception as e:
        return [f"[Image processing error: {e}]"]
```

Photos are uploaded to **imgbb** (`https://api.imgbb.com/1/upload`) via
`kibernikto.utils.image.publish_image_file`. The API key is read from `IMAGE_STORAGE_API_KEY`
env var (or hardcoded fallback in the source — replace it in your env). The returned URL is
wrapped in `pydantic_ai.messages.ImageUrl` and given to the model.

The largest photo variant (`message.photo[-1]`) is selected. Telegram's `get_file` returns
`file_path` that aiogram resolves to a downloadable URL. The bytes are passed straight to imgbb.

To switch to a different image host (e.g. S3), replace the body of `publish_image_file` in
`kibernikto/utils/image.py` — the preprocessor doesn't care about the host.

### Voice & audio

```python
async def _process_voice(self, message: types.Message) -> list[UserContent]:
    if not message.voice and not message.audio:
        return []

    if not SETTINGS.TRANSCRIBE_OPENAI_API_KEY:
        return ["[Voice transcription error: no TRANSCRIBE_OPENAI_API_KEY configured]"]

    voice = message.voice or message.audio
    file = await message.bot.get_file(voice.file_id)
    file_name = os.path.basename(file.file_path)
    file_extension = os.path.splitext(file_name)[1]
    local_file_path = f"{TELEGRAM_SETTINGS.FILES_LOCATION}/{voice.file_unique_id}{file_extension}"
    await message.bot.download_file(file.file_path, local_file_path)
    transcription = await self._transcribe_openai(local_file_path)
    return [f"[Voice transcription]: {transcription}"]
```

Voice and audio messages are downloaded to `TG_FILES_LOCATION` (default `/tmp`) and sent to
OpenAI Whisper via `AsyncOpenAI(...).audio.transcriptions.create(...)`. The result is prefixed with
`[Voice transcription]:` so the model can recognise it as a transcript (and not confuse it with a
literal user message).

The `_transcribe_openai` helper:

```python
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
```

Setting `TRANSCRIBE_OPENAI_API_BASE_URL=https://api.vsegpt.ru:7090/v1` and
`TRANSCRIBE_OPENAI_API_MODEL=stt-openai/whisper-1` routes through vsegpt.

### Documents (PDF only, admin-only)

```python
async def _process_document(self, message: types.Message) -> list[UserContent]:
    if not message.document:
        return []
    if not permissions.is_from_admin(message):
        return ["[Document error: only admin can upload files]"]
    document = message.document
    if document.mime_type != "application/pdf":
        return [f"[Document error: unsupported type {document.mime_type}, only PDF is supported]"]
    # ... download to TG_FILES_LOCATION, then:
    return [f"[Document error: PDF processing not implemented yet for {document.file_name}]"]
```

**PDF processing is a stub.** The current implementation downloads the file to
`TG_FILES_LOCATION` and replies with a marker — the actual parsing (e.g. `pypdf`) is not wired in.
To implement, replace the `TODO` line with a real PDF-to-text call and return a `str` (or
`[document_text]`).

### Reply context

```python
async def _process_reply(self, message: types.Message) -> list[UserContent]:
    reply = message.reply_to_message
    if not reply:
        return []
    if reply.from_user:
        if reply.from_user.id == (await message.bot.me()).id:
            author = "bot (you)"
        elif reply.from_user.username:
            author = f"@{reply.from_user.username}"
        else:
            author = reply.from_user.full_name
    else:
        author = "unknown"
    quoted_parts = await self.process_tg_message(reply)  # recurse
    if not quoted_parts:
        return [f"[Replying to {author}'s message]"]
    return [
        f"[Replying to {author}'s message]:",
        *quoted_parts,
        "[End of quoted message]",
    ]
```

The preprocessor is **recursive** — a reply to a photo, voice, or even another reply is fully
expanded. The quoted message is prepended with `[Replying to <author>]:` and closed with
`[End of quoted message]`. When the author is the bot itself, the label is `bot (you)` so the
model can recognise it as prior context.

### Forwards

```python
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
```

A forward is marked with `[Forwarded from <source>]:` and the actual forwarded content is
**not** included — only the marker. This is a deliberate scope cut: including forwarded media would
require re-uploading photos, re-transcribing voices, etc. If you want the content too, recurse into
`origin.message` (aiogram >= 3.4 supports it) the same way `_process_reply` recurses into
`message.reply_to_message`.

## Order of operations matters

The `parts.extend(...)` order is **caption → reply → photo → forward → voice → document → text**.
This is what the model sees first. For a photo with a caption that is also a reply to a voice
message, the result is:

```python
[
    "the caption text",                                  # _process_caption
    "[Replying to @user]:",
    "[Voice transcription]: hello there",
    "[End of quoted message]",                           # _process_reply
    ImageUrl(url="https://i.ibb.co/..."),                # _process_photo
    "[Forwarded from <source>]:",                        # _process_forward
    # no voice here — quoted voice was inside the reply
    # no document here
    # no text — caption was already added
]
```

Reordering changes how the model weighs caption vs. body. Keep the current order unless you have a
strong reason.

## Replacing the preprocessor

`TelegramMessagePreprocessor` is imported as:

```python
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
```

If you ship a custom preprocessor (e.g. for a different media pipeline), either:

1. Subclass it and override the methods you need, then patch the import in
   `kibernikto/telegram/handlers/conversation.py`.
2. Write a new class with the same `process_tg_message(message) -> list[UserContent] | None`
   signature and replace the import.
