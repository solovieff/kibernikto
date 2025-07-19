import logging

from aiogram import types, enums, F
from aiogram.filters import or_f, and_f
from aiogram.fsm.state import default_state

from kibernikto.utils.ai_executor import get_ready_executor
from kibernikto.utils.permissions import admin_or_public
from . import dispatcher as cd
from ..utils.telegram import reply


@cd.dp.message(
    and_f(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'), ~F.caption.startswith('/'), default_state))
async def private_message(message: types.Message):
    if not admin_or_public(message):
        negative_reply_text = f"Я не отвечаю на вопросы в личных беседах с незакомыми людьми (если это конечно не один из моиз Повелителей " \
                              f"снизошёл до меня). Я передам ваше соообщение мастеру."
        await message.reply(text=negative_reply_text)
        await message.forward(cd.TELEGRAM_SETTINGS.TG_MASTER_ID)
    else:
        user_text = await cd.preprocessor.process_tg_message(message,
                                                             tg_bot=cd.tg_bot)
        if user_text is None:
            return None  # do not reply
        user_ai = await get_ready_executor(message=message)

        await cd.tg_bot.send_chat_action(message.chat.id, 'typing')
        reply_text = await user_ai.heed_and_reply(message=user_text)

        if reply_text is None:
            reply_text = "My iron brain did not generate anything!"

        await reply(message=message, reply_text=reply_text)


# noinspection SpellCheckingInspection
@cd.dp.message(
    or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP))
async def group_message(message: types.Message):
    chat_id = message.chat.id

    if not message.from_user:
        logging.warning(message.md_text)
        return None

    group_ai = await get_ready_executor(message=message)

    if cd.is_reply(message) or group_ai.should_react(message.html_text):
        if cd.TELEGRAM_SETTINGS.TG_FRIEND_GROUP_IDS and chat_id not in cd.TELEGRAM_SETTINGS.TG_FRIEND_GROUP_IDS:
            negative_reply_text = (f"I don't participate in conversations where I'm not invited to join"
                                   f" (unless of course one of my Masters"
                                   f" has deigned to address me). I'll forward your message to someone.")
            print(f"allowed chats: {cd.TELEGRAM_SETTINGS.TG_FRIEND_GROUP_IDS}, given chat: {chat_id}")
            await message.reply(text=negative_reply_text)
            await message.forward(chat_id=cd.TELEGRAM_SETTINGS.TG_MASTER_ID)
            return None

        user_text = await cd.preprocessor.process_tg_message(message,
                                                             tg_bot=cd.tg_bot)
        if user_text is None:
            return None  # do not reply

        await cd.tg_bot.send_chat_action(chat_id, 'typing')
        reply_text = await group_ai.heed_and_reply(message=user_text, author=message.from_user.username)

        await reply(message=message, reply_text=reply_text)


def imported_ok():
    print('\t%-15s%-20s' % ("handlers:", 'private_message, group_message'))
