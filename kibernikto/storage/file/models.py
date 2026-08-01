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
    client_app_info_updated_at: Optional[float] = None
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
        """Compact one-line summary for the system prompt (empty fields omitted)."""
        parts = []
        if self.private_info and self.private_info != "No info yet.":
            parts.append(f"private_info: {self.private_info}")
        if self.public_info:
            parts.append(f"public_info: {self.public_info}")
        parts.append(f"credits: {self.credits}")
        parts.append(f"timezone: {self.timezone}")
        if self.client_app_info:
            parts.append(self.client_app_info)
        return " | ".join(parts)
