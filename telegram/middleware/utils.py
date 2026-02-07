from aiogram.types import TelegramObject, Update, Message


def get_event_message(event: TelegramObject) -> Message | None:
    if isinstance(event, Update) and event.message:
        message: Message = event.message or event.edited_message
        return message
    elif isinstance(event, Message):
        return event
    else:
        return None
