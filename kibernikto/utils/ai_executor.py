from aiogram.types import Message, Chat

from kibernikto.telegram import executor_exists, get_ai_executor_full
from kibernikto.telegram._executor_corral import get_temp_executor


async def get_ready_executor(message: Message, apply_plugins=True):
    chat_id = message.chat.id

    if not executor_exists(chat_id):
        chat_info: Chat = await message.bot.get_chat(chat_id)
    else:
        chat_info = message.chat
    user_ai = get_ai_executor_full(chat=chat_info, user=message.from_user, apply_plugins=apply_plugins)
    return user_ai

async def check_key(message: Message):
    chat_id = message.chat.id
    vse_key = message.text

    async with get_temp_executor(key_id=chat_id, ) as hi_bot:
        hi_message = await hi_bot.heed_and_reply("Поприветствуй своего хозяина!")

