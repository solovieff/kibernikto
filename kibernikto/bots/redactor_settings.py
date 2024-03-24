from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_TEXT = """
    Обогати текст феминитивами и в ответе верни только то, что получилось без своих комментариев:
    {message}
"""


class RedactorSetting(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='REDACTOR_')
    OPENAI_API_MODEL: str = "mistralai/mistral-large"
    OPENAI_BASE_URL: str = "https://api.vsegpt.ru:6070/v1"
    OPENAI_API_KEY: str | None = None
    OPENAI_MAX_TOKENS: int = 1200

    OPENAI_WHO_AM_I: str = ""
    MESSAGE: str = _DEFAULT_TEXT


REDACTOR_SETTINGS = RedactorSetting()
