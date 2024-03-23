from pydantic import HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_TEXT = """
    Обогати текст ругательствами и оскорблениями и в ответе верни только то, что получилось без своих комментариев:
    {message}
"""


class RedactorSetting(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='REDACTOR_')
    OPENAI_API_MODEL: str = "mistralai/mistral-large"
    OPENAI_BASE_URL: HttpUrl = "https://api.vsegpt.ru:6070/v1"
    OPENAI_API_KEY: str | None = None

    OPENAI_WHO_AM_I: str = ""
    MESSAGE: str = _DEFAULT_TEXT
