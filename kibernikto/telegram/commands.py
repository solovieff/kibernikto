import logging

from aiogram import Bot, types, enums
from aiogram.filters import Command, CommandObject
from pydantic_settings import BaseSettings
from kibernikto.telegram.telegram_bot import TelegramBot

from kibernikto.utils.permissions import is_from_admin
from kibernikto.utils.telegram import reply


class CommandSettings(BaseSettings):
    TG_MASTER_ID: int
    TG_MASTER_IDS: list = []
    TG_ADMIN_COMMANDS_ALLOWED: bool = True


PP_SETTINGS = CommandSettings()

if PP_SETTINGS.TG_ADMIN_COMMANDS_ALLOWED:
    from kibernikto.telegram import dispatcher, get_ai_executor

    print('\t%-20s%-20s' % ("service commands:", '["/system_message"]'))


    @dispatcher.dp.message(Command(commands=["system_message"]))
    async def private_message(message: types.Message, command: CommandObject):
        if is_from_admin(message) and PP_SETTINGS.TG_ADMIN_COMMANDS_ALLOWED:
            if message.chat.type == enums.ChatType.PRIVATE:
                user_ai: TelegramBot = get_ai_executor(message.from_user.id)
                if user_ai is None:
                    await message.reply(f"🥸 Похоже мне ещё никто не писал. Дам информацию после первого сообщения.")
                    return None
                text = f"Меня зовут ```{user_ai.full_config.name}```"
                f"Мой систем промт ```{user_ai.about_me['content']}```"
                f"Моя модель ```{user_ai.full_config.model}```"
                f"Моя температура ```{user_ai.full_config.temperature}```"
                f"Откликаюсь на ```{str(user_ai.full_config.reaction_calls)}```"
                await reply(message, text)

            else:
                await message.reply(f"❌Не при всех!")
        else:
            await message.reply(f"❌Вам нельзя!")
else:
    print('\t%-20s%-20s' % ("service commands:", 'disabled'))
