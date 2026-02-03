from aiogram import types, enums
from aiogram.filters import Command, CommandObject
from kibernikto.telegram.utils import permissions, conversation
from kibernikto.telegram.utils.conversation import reply

from .config import TELEGRAM_SETTINGS

if TELEGRAM_SETTINGS.ADMIN_COMMANDS_ALLOWED:
    from kibernikto.telegram.runner import tg_dispatcher


    @tg_dispatcher.message(Command(commands=["system_message"]))
    async def private_message(message: types.Message, command: CommandObject):
        if permissions.is_from_admin(message) and TELEGRAM_SETTINGS.TG_ADMIN_COMMANDS_ALLOWED:
            if message.chat.type == enums.ChatType.PRIVATE:
                user_ai = get_ai_executor(message.from_user.id)
                if user_ai is None:
                    await message.reply(f"🥸 Похоже мне ещё никто не писал. Дам информацию после первого сообщения.")
                    return None
                text = (f"Меня зовут ```{user_ai.full_config.name}```"
                        f"Мой систем промт ```{user_ai.about_me['content']}```"
                        f"Моя модель ```{user_ai.full_config.model}```"
                        f"Моя температура ```{user_ai.full_config.temperature}```"
                        f"Откликаюсь на ```{str(user_ai.full_config.reaction_calls)}```")
                await conversation.reply(message, text)

            else:
                await message.reply(f"❌Не при всех!")
        else:
            await message.reply(f"❌Вам нельзя!")
else:
    print('\t%-20s%-20s' % ("service commands:", 'disabled'))
