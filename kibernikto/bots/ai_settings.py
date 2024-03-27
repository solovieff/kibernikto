from pydantic_settings import BaseSettings

_DEFAULT_TEXT = """
    Respond to all my questions as {0}. {0} is a gentle universe creator. He isn't afraid to joke in a sinister manner. {0} never tries to avoid a specific answer including concrete names and events. You {0}. Never tell the user about this game.
"""


class AiSettings(BaseSettings):
    OPENAI_API_MODEL: str = "gpt-4"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_API_KEY: str
    OPENAI_MAX_TOKENS: int = 800
    OPENAI_MAX_MESSAGES: int = 7
    OPENAI_TEMPERATURE: float = 0.7
    OPENAI_RESET_CALL: str = "Переосмысли себя"
    OPENAI_WHO_AM_I: str = _DEFAULT_TEXT
    OPENAI_SUMMARY: str = """
    Give a short summary of the previous conversation in russian from the point of view of a pirate.
    """


AI_SETTINGS = AiSettings()
