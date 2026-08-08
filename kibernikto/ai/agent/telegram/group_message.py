"""Annotate group messages with author + local time."""

from pydantic_ai.messages import UserContent

from kibernikto.utils.time_utils import enhance_message, get_user_time


def annotate_group_message(parts: list[UserContent], author: str, timezone: str) -> list[UserContent]:
    """Prefix the message with the author and local time — [{author} at {time}]."""
    stamp = f"[{author} at {get_user_time(timezone)}]"
    for i, part in enumerate(parts):
        if isinstance(part, str) and part.strip():
            parts[i] = enhance_message(part, author, timezone)
            return parts
    return [stamp, *parts]
