"""Settings for the gated travel coordinator."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TravelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_TRAVEL_')

    ENABLED: bool = False
    MODEL_NAME: str | None = None
    MODEL_MAX_TOKENS: int = Field(default=8192, ge=1)
    MAX_TOOL_CALLS: int = Field(default=40, ge=1)

    @property
    def active(self) -> bool:
        """Coordinator is on and at least one specialist is left."""
        from .kiwi.config import KIWI_SETTINGS
        from .travala.config import TRAVALA_SETTINGS
        from .tutu.config import TUTU_SETTINGS

        return self.ENABLED and any(s.ENABLED for s in (KIWI_SETTINGS, TRAVALA_SETTINGS, TUTU_SETTINGS))


TRAVEL_SETTINGS = TravelSettings()
