"""Business expert configuration."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BusinessSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_BUSINESS_')

    DADATA_TOKEN: SecretStr | None = None
    MODEL_NAME: str | None = None
    MIN_CREDITS: int = Field(default=2000, ge=0)
    MAX_TOOL_CALLS: int = Field(default=20, ge=1)

    @property
    def configured(self) -> bool:
        """The MCP accepts exactly an API key and secret key separated by a colon."""
        if self.DADATA_TOKEN is None:
            return False
        parts = self.DADATA_TOKEN.get_secret_value().split(':')
        return len(parts) == 2 and all(p and p == p.strip() for p in parts)


BUSINESS_SETTINGS = BusinessSettings()
