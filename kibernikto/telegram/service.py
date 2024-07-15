from typing import Dict, Any

from aiogram import enums
from aiogram.types import Update, ErrorEvent
from pydantic_settings import BaseSettings


class ServiceSettings(BaseSettings):
    TG_SERVICE_GROUP_ID: int | None = None


S_SETTINGS = ServiceSettings()

if S_SETTINGS.TG_SERVICE_GROUP_ID:
    from kibernikto.telegram import comprehensive_dispatcher

    print('\t%-20s%-20s' % ("service messages:", S_SETTINGS.TG_SERVICE_GROUP_ID))


    # runs when message comes
    @comprehensive_dispatcher.dp.update.outer_middleware()
    async def service_messages_middleware(handler, event: Update, data: Dict[str, Any]) -> Any:
        if not event or not event.message or event.message.chat.type != enums.ChatType.PRIVATE:
            return await handler(event, data)
        if S_SETTINGS.TG_SERVICE_GROUP_ID is not None:
            message = event.message
            await message.forward(chat_id=S_SETTINGS.TG_SERVICE_GROUP_ID)
        return await handler(event, data)


    @comprehensive_dispatcher.dp.error.outer_middleware()
    async def service_errors_middleware(handler, event: ErrorEvent, data: Dict[str, Any]) -> Any:
        if not event:
            return await handler(event, data)

        if not event.update or not event.update.message:
            return await handler(event, data)

        user_message = event.update.message

        if S_SETTINGS.TG_SERVICE_GROUP_ID is not None:
            service_message = f"🔥🔥🔥 {user_message.from_user.username} {user_message.content_type}: {user_message.md_text} {event.exception}"
            await event.update.bot.send_message(S_SETTINGS.TG_SERVICE_GROUP_ID, service_message)

        return await handler(event, data)
else:
    print('\t%-20s%-20s' % ("service messages:", 'disabled'))
