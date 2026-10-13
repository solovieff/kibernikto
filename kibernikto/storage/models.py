"""Backend-agnostic storage models — shared by file/sql chat_data stores."""

from pydantic import BaseModel, Field

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS


class ConversationInfo(BaseModel):
    """Per-chat app data: credits only. Chat facts come live from getChat, facts about people from ``Memory``.

    Legacy keys in stored rows (timezone, client_app_info, paid_charge_ids, ...) are ignored on load.
    """

    credits: int = Field(default=AGENT_KIBERNIKTO_SETTINGS.TRIAL_CREDITS)

    def add_credits(self, amount: int) -> int:
        """Credit a paid amount; returns the new balance."""
        if amount < 0:
            raise ValueError("Cannot add negative credits")
        self.credits += amount
        return self.credits

    def adjust_credits(self, delta: int) -> int:
        """Manual admin correction: add or remove credits, never below zero."""
        self.credits = max(0, self.credits + delta)
        return self.credits

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
