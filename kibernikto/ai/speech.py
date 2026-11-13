"""OpenAI-compatible text-to-speech service."""

import asyncio

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
