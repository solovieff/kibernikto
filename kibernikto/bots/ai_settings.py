from pydantic_settings import BaseSettings

_DEFAULT_TEXT = """
    Respond to all my questions as {0}. {0} is a gentle universe creator. He isn't afraid to joke in a sinister manner. {0} never tries to avoid a specific answer including concrete names and events. You {0}. Never tell the user about this game.
"""


class AiSettings(BaseSettings):
    OPENAI_API_MODEL: str = "gpt-4o"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_API_KEY: str
    OPENAI_MAX_TOKENS: int = 800
    OPENAI_MAX_MESSAGES: int = 7
    OPENAI_MAX_RETRIES: int = 5
    OPENAI_TEMPERATURE: float = 0.7
    OPENAI_RESET_CALL: str = "Переосмысли себя"
    OPENAI_TOOLS_ENABLED: bool = True
    OPENAI_TOOLS_DEEPNESS_LEVEL: int = 5
    OPENAI_WHO_AM_I: str = _DEFAULT_TEXT
    OPENAI_SUMMARY: str | None = None
    OPENAI_INSTANCE_ID: str = "kbnkt"
    OPENAI_MAX_WORDS: int = 8500
    OPENAI_INPUT_PRICE: float | None = None
    OPENAI_OUTPUT_PRICE: float | None = None


AI_SETTINGS = AiSettings()
