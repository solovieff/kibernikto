"""Bot identity helpers — built from Telegram getMe / getMyDescription."""

_bot_identity: str | None = None


def set_bot_identity(identity: str | None) -> None:
    """Store the bot's own identity text for system-prompt injection."""
    global _bot_identity
    _bot_identity = identity


def get_bot_identity() -> str | None:
    return _bot_identity


def format_bot_identity(
    *,
    username: str | None,
    first_name: str | None,
    short_description: str | None,
    description: str | None,
    name: str | None,
) -> str | None:
    """Build a compact bot-parameters line from Telegram getMe/*Description."""
    parts: list[str] = []
    # Don't use "You are" — it clashes with the main WHO_AM_I instructions.
    if username:
        parts.append(f"username: @{username}")
    display = name or first_name or ""
    if display:
        parts.append(f"display_name: {display}")
    if short_description:
        parts.append(f"short_description: {short_description}")
    if description:
        parts.append(f"description: {description}")
    if not parts:
        return None
    return "[Your Telegram bot parameters] " + " | ".join(parts)
