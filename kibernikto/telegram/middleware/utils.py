from aiogram.types import TelegramObject, Update, Message


def get_event_message(event: TelegramObject) -> Message | None:
    """Extract the relevant ``Message`` from any aiogram event object.

    Handles both raw ``Update`` (where the message may be in ``.message`` or
    ``.edited_message``) and direct ``Message`` events that middlewares receive
    when registered on ``dispatcher.message`` / ``dispatcher.edited_message``.
    """
    if isinstance(event, Update):
        return event.message or event.edited_message
    if isinstance(event, Message):
        return event
    return None
