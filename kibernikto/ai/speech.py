"""OpenAI-compatible text-to-speech service."""

import asyncio
import re

from openai import AsyncOpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='TTS_OPENAI_', env_ignore_empty=True)

    API_KEY: SecretStr | None = None
    API_BASE_URL: str = 'https://openrouter.ai/api/v1'
    API_MODEL: str = 'elevenlabs/eleven-v4'
    API_VOICE: str = 'adam'
    API_DELIVERY_TAGS: str = '[tired] [low, gravelly] [cynical] [dark]'
    API_PROVIDER_OPTIONS: dict[str, dict[str, object]] | None = None


SPEECH_SETTINGS = SpeechSettings()
TTS_TIMEOUT_SECONDS = 30.0
# Eleven v4 accepts at most 10,000 characters per request; keep a margin for delivery tags.
TTS_CHUNK_LIMIT = 9000

_SPEECH_CLEANUPS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'```.*?```', re.DOTALL), ''),
    (re.compile(r'!?\[([^\]]+)\]\([^)\s]*\)'), r'\1'),
    (re.compile(r'https?://\S+'), ''),
    (re.compile(r'^\s{0,3}(?:#{1,6}|>|[-*+])\s+', re.MULTILINE), ''),
    (re.compile(r'[`*]+|(?<!\w)_+|_+(?!\w)'), ''),
    (re.compile(r'[ \t]{2,}'), ' '),
    (re.compile(r'[ \t]+$', re.MULTILINE), ''),
    (re.compile(r'\n{3,}'), '\n\n'),
)


def prepare_for_speech(text: str) -> str:
    """Drop what sounds wrong aloud: code blocks, URLs, Markdown markers (link labels stay)."""
    for pattern, replacement in _SPEECH_CLEANUPS:
        text = pattern.sub(replacement, text)
    return text.strip()


def split_for_speech(text: str, limit: int = TTS_CHUNK_LIMIT) -> list[str]:
    """Split on paragraph, sentence or word boundaries so no chunk exceeds ``limit`` characters."""
    chunks: list[str] = []
    rest = text.strip()
    while len(rest) > limit:
        window = rest[:limit]
        # Keep the sentence period with its chunk; fall back to a hard cut when no boundary is late enough.
        end = next((i + len(sep.rstrip(' ')) for sep in ('\n\n', '\n', '. ', ' ')
                    if (i := window.rfind(sep)) > limit // 2), limit)
        chunks.append(rest[:end].strip())
        rest = rest[end:].strip()
    if rest:
        chunks.append(rest)
    return chunks


async def synthesize_speech(text: str) -> bytes:
    """Convert text to MP3 with an OpenAI-compatible speech endpoint."""
    if not SPEECH_SETTINGS.API_KEY:
        raise ValueError('TTS_OPENAI_API_KEY is not configured')
    async with asyncio.timeout(TTS_TIMEOUT_SECONDS), AsyncOpenAI(
        api_key=SPEECH_SETTINGS.API_KEY.get_secret_value(), base_url=SPEECH_SETTINGS.API_BASE_URL,
        timeout=TTS_TIMEOUT_SECONDS, max_retries=0,
    ) as client:
        spoken_text = text
        if SPEECH_SETTINGS.API_MODEL.startswith('elevenlabs/') and SPEECH_SETTINGS.API_DELIVERY_TAGS.strip():
            spoken_text = f'{SPEECH_SETTINGS.API_DELIVERY_TAGS.strip()} {text}'
        response = await client.audio.speech.create(
            model=SPEECH_SETTINGS.API_MODEL, voice=SPEECH_SETTINGS.API_VOICE,
            input=spoken_text, response_format='mp3',
            extra_body={'provider': {'options': SPEECH_SETTINGS.API_PROVIDER_OPTIONS}}
            if SPEECH_SETTINGS.API_PROVIDER_OPTIONS else None,
        )
        if not response.content:
            raise ValueError('Speech service returned empty audio')
        return response.content
