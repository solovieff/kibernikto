"""Time helpers — user timezone formatting and message annotation."""

from datetime import datetime
from zoneinfo import ZoneInfo


def get_user_time(timezone: str = "Europe/Moscow") -> str:
    """Current time string in the user's timezone."""
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("Europe/Moscow")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M")


def enhance_message(message: str, author: str | None = None, timezone: str = "Europe/Moscow") -> str:
    """Prefix a message with timestamp and optional author."""
    time_str = get_user_time(timezone)
    prefix = f"[{author} at {time_str}]" if author else f"[{time_str}]"
    return f"{prefix} {message}"
