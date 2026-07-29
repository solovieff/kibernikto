from typing import Optional

from pydantic import BaseModel, Field

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS


class ConversationInfo(BaseModel):
    """Per-user data: private info, credits and model balancing."""

    tg_id: Optional[int] = None
    private_info: str = "No info yet."
    public_info: str = ""
    credits: int = Field(default=AGENT_KIBERNIKTO_SETTINGS.TRIAL_CREDITS)
    timezone: str = "Europe/Moscow"
    client_app_info: str = ""
    last_pinned_message: Optional[str] = None

    def charge(self, effort: int = 1, dependent: bool = False) -> int:
        """Spend credits proportional to effort; dependent calls cost less."""
        cost = max(1, effort // (2 if dependent else 1))
        self.credits = max(0, self.credits - cost)
        return self.credits

    @property
    def model_name(self) -> str:
        """Pick model by credit balance: poor / medium / rich."""
        s = AGENT_KIBERNIKTO_SETTINGS
        if self.credits < s.POOR_CREDITS:
            return s.POOR_MODEL
        if self.credits >= s.RICH_CREDITS:
            return s.RICH_MODEL
        return s.MEDIUM_MODEL

    def as_string(self) -> str:
        """Compact one-line summary for the system prompt."""
        return (
            f"private_info: {self.private_info} | "
            f"public_info: {self.public_info or 'none'} | "
            f"credits: {self.credits} | "
            f"timezone: {self.timezone}"
        )