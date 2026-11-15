"""here.now publishing expert configuration."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class HereNowSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_HERENOW_')

    # Opt-in: without a key the expert never loads (anonymous sites expire in 24 hours).
    ENABLED: bool = False
    API_KEY: SecretStr | None = None
    BASE_URL: str = 'https://here.now'
    WORKSPACE: str | None = None  # workspace subdomain the sites belong to; unset = personal account
    MODEL_NAME: str | None = None
    MODEL_MAX_TOKENS: int = Field(default=32000, ge=1)  # the whole page is one tool argument
    MAX_TOOL_CALLS: int = Field(default=16, ge=1)
    MAX_FILES: int = Field(default=12, ge=1)
    MAX_TOTAL_BYTES: int = Field(default=2_000_000, ge=1)
    REQUEST_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0)

    @property
    def key(self) -> str | None:
        """Usable key; an empty env var is the same as no key at all."""
        return (self.API_KEY.get_secret_value().strip() or None) if self.API_KEY is not None else None

    @property
    def active(self) -> bool:
        return self.ENABLED and self.key is not None


HERENOW_SETTINGS = HereNowSettings()
