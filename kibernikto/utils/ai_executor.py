from aiogram.types import Message, Chat

from kibernikto.telegram import executor_exists, get_ai_executor_full


async def get_ready_executor(message: Message, apply_plugins=True):
    chat_id = message.chat.id

    if not executor_exists(chat_id):
        chat_info: Chat = await message.bot.get_chat(chat_id)
    else:
        chat_info = message.chat
    user_ai = get_ai_executor_full(chat=chat_info, user=message.from_user, apply_plugins=apply_plugins)
    return user_ai
