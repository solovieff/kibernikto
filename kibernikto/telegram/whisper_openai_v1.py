from openai import AsyncOpenAI
from openai.resources.audio import AsyncTranscriptions
from pydantic_settings import BaseSettings


class PreprocessorSettings(BaseSettings):
    OPENAI_API_KEY: str = "sk-XXXXXXXXXXXXXXXX"
    OPENAI_API_MODEL: str = "stt-openai/whisper-1"
    OPENAI_API_BASE_URL: str = "https://api.vsegpt.ru/v1"
    MP3_FILE_LOCATION: str = "/tmp/tg_voices"


SETTINGS = PreprocessorSettings()


async def _process_mp3(file_id: str):
    client = AsyncOpenAI(base_url=SETTINGS.OPENAI_API_BASE_URL,
                         api_key=SETTINGS.OPENAI_API_KEY)
    audio_client: AsyncTranscriptions = AsyncTranscriptions(client=client)

    local_file_path = f"{SETTINGS.MP3_FILE_LOCATION}/{file_id}.mp3"

    with open(local_file_path, "rb") as audio_file:
        transcription = await audio_client.create(language="ru", model=SETTINGS.VOICE_OPENAI_API_MODEL,
                                                  file=audio_file,
                                                  response_format="text")
        return transcription.text
