import asyncio
import traceback
from typing import Dict, Any

from aiogram import enums, Bot
from aiogram.types import Update, ErrorEvent, Message
from pydantic_settings import BaseSettings

from kibernikto.utils.permissions import is_from_admin


class ServiceSettings(BaseSettings):
    TG_SERVICE_GROUP_ID: int | None = None


S_SETTINGS = ServiceSettings()

if S_SETTINGS.TG_SERVICE_GROUP_ID:
    from kibernikto.telegram import dispatcher

    print('\t%-20s%-20s' % ("service messages:", S_SETTINGS.TG_SERVICE_GROUP_ID))


    async def forward_message_service_group(message: Message) -> None:
        try:
            if not is_from_admin(message):
                await message.forward(chat_id=S_SETTINGS.TG_SERVICE_GROUP_ID)
        except Exception as e:
            traceback.print_exc()
            print('failed to send the service message')


    async def send_message_to_service(bot: Bot, service_message: str) -> None:
        try:
            await bot.send_message(S_SETTINGS.TG_SERVICE_GROUP_ID, service_message)
        except Exception as e:
            print('failed to send the service message')


    # runs when message comes
    @dispatcher.dp.update.outer_middleware()
    async def service_messages_middleware(handler, event: Update, data: Dict[str, Any]) -> Any:
        if not event or not event.message or event.message.chat.type != enums.ChatType.PRIVATE:
            return await handler(event, data)
        asyncio.create_task(forward_message_service_group(event.message))
        return await handler(event, data)


    @dispatcher.dp.error.outer_middleware()
    async def service_errors_middleware(handler, event: ErrorEvent, data: Dict[str, Any]) -> Any:
        if not event:
            return await handler(event, data)

        if not event.update or not event.update.message:
            return await handler(event, data)

        user_message = event.update.message

        service_message = f"🔥🔥🔥 {user_message.from_user.username} {user_message.content_type}: {user_message.md_text} {event.exception}"
        asyncio.create_task(send_message_to_service(bot=event.update.bot, service_message=service_message))

        return await handler(event, data)
else:
    print('\t%-20s%-20s' % ("service messages:", 'disabled'))
