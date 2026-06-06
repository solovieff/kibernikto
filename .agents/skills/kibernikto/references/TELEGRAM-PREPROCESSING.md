# Telegram Preprocessing

Source: `kibernikto/telegram/pre_processors/`

## Purpose

Converts an aiogram `Message` into `list[UserContent]` — the format pydantic-ai accepts as agent
input. `UserContent` items can be plain strings, `ImageUrl`, or binary parts.

## Class Structure

```
TelegramMessagePreprocessor     (_default.py — base, also the default implementation)
```

`TelegramAgent` holds a `pre_processor` property (defaults to
`DefaultTelegramMessagePreprocessor`). Override it in a subclass to change how messages are parsed.

## `process_tg_message(message)` Dispatch

The method inspects `message.content_type` and delegates:

| Content type | Handler | Result |
|---|---|---|
| `TEXT` | Extract text | `str` added to list |
| `PHOTO` | Upload to imgbb via `publish_image_file` | `ImageUrl` added to list |
| `VOICE` / `AUDIO` | Download + Whisper transcription | transcribed `str` added |
| `DOCUMENT` (PDF) | *(stub)* not implemented yet | skipped |
| `CAPTION` | Treated as text alongside photo | `str` added |
| `reply_to_message` | Recursive call on the replied-to message | prepended to list |
| `forward_origin` | Extracts origin metadata as text prefix | prepended |
| Any in `IGNORED_TYPES` | Silently skipped | `None` returned for full message |

`IGNORED_TYPES` = `{STICKER, NEW_CHAT_MEMBERS, LEFT_CHAT_MEMBER, ...}` — defined as a module-level
constant in `_default.py`.

Returns `None` if the message type is ignored or produced no content, which signals the handler to
skip the LLM call entirely.

## Configuration (`PreprocessorSettings`, prefix `TRANSCRIBE_`)

See [Configuration](./CONFIGURATION.md#preprocessorsettings-transcribe_) for all env vars.

Voice transcription is disabled by default (`TRANSCRIBE_PROCESSOR=None`). Set it to `"openai"` and
provide `TRANSCRIBE_OPENAI_API_KEY` to enable Whisper.

## Image Upload

`publish_image_file(bot, file_id)` in `kibernikto/utils/image.py`:
- Downloads the file from Telegram
- Uploads to imgbb using `IMGBB_API_KEY` env var
- Returns a public URL → wrapped as `ImageUrl` for the model

Requires `IMGBB_API_KEY` to be set. Without it, photo content is skipped.

## Custom Preprocessor

Subclass `TelegramMessagePreprocessor` and override `process_tg_message`:

```python
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor
from kibernikto.telegram.agent import TelegramAgent, set_telegram_agent

class MyPreprocessor(TelegramMessagePreprocessor):
    async def process_tg_message(self, message):
        # custom logic — call super() or rewrite entirely
        ...

class MyAgent(TelegramAgent):
    @property
    def pre_processor(self):
        return MyPreprocessor()

set_telegram_agent(MyAgent(...))
```
