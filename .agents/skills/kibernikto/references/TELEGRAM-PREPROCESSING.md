# Telegram preprocessing

Source: `kibernikto/telegram/pre_processors/_default.py`.
Import `TelegramMessagePreprocessor` from `kibernikto.telegram.pre_processors`;
there is no separate `DefaultTelegramMessagePreprocessor` class.

## Actual processing order

`process_tg_message(message, *, _reply_depth=0)` returns `list[UserContent] | None`.
For ignored service/sticker types it sends `Unknown message type :(` then returns
None; this is **not silent**. Otherwise it collects these parts in order:

1. Caption text.
2. Quoted reply, recursively preprocessed with author markers, bounded to depth 3.
3. Largest photo: download bytes, save to Telegram media namespace, publish URL,
   then add `ImageUrl`; errors become explanatory text markers.
4. Forward-origin marker for user/chat/channel/hidden-user origins.
5. Voice or audio transcription.
6. Document error/stub marker.
7. Message text.

An empty collection returns None and the agent skips the model call. Error markers
are content, so they can reach the model. `MODEL_MODALITIES` currently does not gate
these handlers. A caption is a field processed alongside media, not its own Telegram
content type.

## Images and storage

The preprocessor uses `tg_media_store` from `kibernikto/storage/singletons.py` and
`image_hosting` from `kibernikto/utils/image_hosting.py`. It stores original photo
bytes under the `telegram` media namespace and independently publishes a model-fetchable
URL. Failure to archive is logged; failure to publish adds an error marker.

Public hosting currently supports imgbb with `IMAGE_STORAGE_API_KEY`, selected by
`IMAGE_HOSTING_PROVIDER=imgbb`. `IMAGE_STORAGE_EXPIRATION=0` omits a TTL. S3 storage
is not automatically public URL hosting. Old `publish_image_file(bot, file_id)` and
`IMGBB_API_KEY` instructions were incorrect; the legacy wrapper takes bytes and name.

## Voice and documents

The **presence of `TRANSCRIBE_OPENAI_API_KEY`** enables the current voice/audio path.
`PROCESSOR` is declared but not checked; setting it to elevenlabs does not select an
ElevenLabs implementation, and leaving it None does not disable a configured key.
Downloaded audio goes through local storage temp paths and is cleaned in `finally`
after transcription. Output is prefixed `[Voice transcription]:`.

`TRANSCRIBE_OPENAI_API_MODEL`, `OPENAI_API_BASE_URL` and `OPENAI_API_LANGUAGE`
configure the OpenAI-compatible call. `MIN_COMPLEX_SECONDS` is not used. Some
get-file/download failures return markers, but exceptions raised during transcription
itself can escape; don't promise universal soft failure handling.

Documents require admin access in this preprocessor. Non-PDF documents produce an
unsupported-type marker. PDFs still produce a **not implemented** marker; no PDF
extraction is wired. Do not install a parser merely to audit the docs.

## Custom preprocessor

```python
from aiogram.types import Message
from pydantic_ai.messages import UserContent
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
from pydantic_ai.models.test import TestModel

class TextOnly(TelegramMessagePreprocessor):
    async def process_tg_message(
        self, message: Message, *, _reply_depth: int = 0,
    ) -> list[UserContent] | None:
        return [message.text] if message.text else None

agent = TelegramAgent(model=TestModel(), pre_processor=TextOnly(), history_storage=None)
```

Keep the recursion keyword if calling the default reply-processing implementation.
Each TelegramAgent owns its preprocessor instance, while module-level `SETTINGS`
and `IGNORED_TYPES` remain shared. Treat them as read-only in production; patch and
restore them only in isolated tests. For startup/registration see [Handlers](TELEGRAM-HANDLERS.md).
