"""Tariff — one object that answers what a chat's balance buys: tier and paid-expert access."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS

type Tier = Literal["poor", "medium", "rich"]

# What each credit-gated expert does, in the words a user would ask for it.
GATED_EXPERT_PURPOSE: dict[str, str] = {
    "herenow": "build and publish a website",
    "vkusvill": "grocery shopping at VkusVill",
    "travel": "flights, hotels, trains, buses",
    "business": "Russian company lookup by INN/OGRN",
}


def credit_tier(credits: int) -> Tier:
    """Return the tier for a credit balance; thresholds mirror ``ConversationInfo.model_name``."""
    s = AGENT_KIBERNIKTO_SETTINGS
    if credits < s.POOR_CREDITS:
        return "poor"
    if credits >= s.RICH_CREDITS:
        return "rich"
    return "medium"


def expert_allowed(*, credits: int | None, is_personal: bool) -> bool:
    """Paid experts: personal chats in the rich tier only; a group chat never sees them."""
    if not is_personal or credits is None:
        return False
    return credit_tier(credits) == "rich"


def enabled_gated_experts() -> tuple[str, ...]:
    """Credit-gated experts switched on by settings (the same switches ``build_multi_agent`` uses)."""
    from kibernikto.ai.agent.addons.business.config import BUSINESS_SETTINGS
    from kibernikto.ai.agent.addons.herenow.config import HERENOW_SETTINGS
    from kibernikto.ai.agent.addons.travel.config import TRAVEL_SETTINGS
    from kibernikto.ai.agent.addons.vkusvill.config import VKUSVILL_SETTINGS

    switches = {
        "vkusvill": VKUSVILL_SETTINGS.ENABLED,
        "travel": TRAVEL_SETTINGS.active,
        "business": BUSINESS_SETTINGS.active,
        "herenow": HERENOW_SETTINGS.active,
    }
    return tuple(name for name, on in switches.items() if on)


@dataclass(frozen=True)
class Tariff:
    """Balance + chat kind -> tier and which paid experts are open; the single source of that rule."""

    credits: int
    is_personal: bool = True
    gated: tuple[str, ...] = field(default_factory=lambda: enabled_gated_experts())

    @property
    def tier(self) -> Tier:
        return credit_tier(self.credits)

    @property
    def experts_open(self) -> bool:
        return expert_allowed(credits=self.credits, is_personal=self.is_personal)

    @property
    def credits_to_experts(self) -> int:
        """Credits still missing for the rich tier; 0 when reached."""
        return max(0, AGENT_KIBERNIKTO_SETTINGS.RICH_CREDITS - self.credits)

    def experts_line(self) -> str | None:
        """Locked paid experts with the reason; None when none is enabled or all are open (nothing to tell)."""
        if not self.gated or self.experts_open:
            return None
        rich = AGENT_KIBERNIKTO_SETTINGS.RICH_CREDITS
        listing = ", ".join(f"{name} ({GATED_EXPERT_PURPOSE.get(name, 'specialist')})" for name in self.gated)
        rule = f"paid experts need a private chat and >={rich} credits"
        if not self.is_personal:
            return f"experts: locked: {listing} | reason: group chats never get them, write in a private chat | rule: {rule}"
        return (f"experts: locked: {listing} | reason: {self.credits_to_experts} more credits needed, "
                f"top up with /pay | rule: {rule}")

    def balance_text(self) -> str:
        """User-facing /balance message: balance, tier, expert access."""
        lines = [f"💳 Balance: {self.credits} credits ({self.tier} tier). Top up: /pay [stars]"]
        if not self.gated or self.experts_open:
            return lines[0]
        listing = ", ".join(f"{name} — {GATED_EXPERT_PURPOSE.get(name, 'specialist')}" for name in self.gated)
        if not self.is_personal:
            lines.append(f"🔒 Experts are available in a private chat only: {listing}")
        else:
            lines.append(f"🔒 Experts need {self.credits_to_experts} more credits: {listing}")
        return "\n".join(lines)
