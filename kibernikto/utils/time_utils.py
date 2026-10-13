"""Time helpers — user timezone formatting and message annotation."""

from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Europe/Moscow"  # No per-chat timezone is stored; everything uses this.


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def get_user_time(timezone: str = DEFAULT_TIMEZONE) -> str:
    """Current time string in the user's timezone."""
    return datetime.now(_zone(timezone)).strftime("%Y-%m-%d %H:%M")


def get_user_date(timezone: str = DEFAULT_TIMEZONE) -> str:
    """Today with weekday and zone — day granularity keeps the prompt cache stable all day."""
    return datetime.now(_zone(timezone)).strftime(f"%Y-%m-%d, %A ({timezone})")


def enhance_message(message: str, author: str | None = None, timezone: str = DEFAULT_TIMEZONE) -> str:
    """Prefix a message with timestamp and optional author."""
    time_str = get_user_time(timezone)
    prefix = f"[{author} at {time_str}]" if author else f"[{time_str}]"
    return f"{prefix} {message}"
