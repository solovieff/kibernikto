from aiogram import Bot, Dispatcher, types, enums, F
from aiogram.filters import or_f, and_f
from aiogram.fsm.context import FSMContext
from aiogram.types import User, BotCommand, Chat
from kibernikto.utils.permissions import admin_or_public
from kibernikto.utils.text import split_text_by_sentences
from ._executor_corral import get_ai_executor_full, executor_exists
from . import comprehensive_dispatcher as cd
from aiogram.fsm.state import State, StatesGroup, any_state, default_state


@cd.dp.message(
    and_f(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'), ~F.caption.startswith('/'), default_state))
async def private_message(message: types.Message):
    user_id = message.from_user.id

    if not admin_or_public(message):
        negative_reply_text = f"Я не отвечаю на вопросы в личных беседах с незакомыми людьми (если это конечно не один из моиз Повелителей " \
                              f"снизошёл до меня). Я передам ваше соообщение мастеру."
        await cd.tg_bot.send_message(user_id,
                                     negative_reply_text)
        await cd.tg_bot.send_message(cd.TELEGRAM_SETTINGS.TG_MASTER_IDS[0],
                                     f"{message.from_user.username}: {message.md_text}")
    else:
        # TODO: plugins should be reworked and combined with preprocessor
        user_text = await cd.preprocessor.process_tg_message(message,
                                                             tg_bot=cd.tg_bot)
        if user_text is None:
            return None  # do not reply
        if not executor_exists(user_id):
            chat_info: Chat = await cd.tg_bot.get_chat(user_id)
        else:
            chat_info = message.chat
        user_ai = get_ai_executor_full(chat=chat_info, user=message.from_user)

        await cd.tg_bot.send_chat_action(message.chat.id, 'typing')
        reply_text = await user_ai.heed_and_reply(message=user_text, author=message.from_user.username)

        if reply_text is None:
            reply_text = "My iron brain did not generate anything!"

        chunks = split_text_by_sentences(reply_text, cd.TELEGRAM_SETTINGS.TG_MAX_MESSAGE_LENGTH)
        for chunk in chunks:
            await message.reply(text=chunk)


# noinspection SpellCheckingInspection
@cd.dp.message(
    or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP))
async def group_message(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if cd.TELEGRAM_SETTINGS.TG_FRIEND_GROUP_IDS and chat_id not in cd.TELEGRAM_SETTINGS.TG_FRIEND_GROUP_IDS:
        negative_reply_text = (f"Я не общаюсь в беседах, в которых мне не велено участвовать"
                               f" (если это конечно не один из моих Повелителей"
                               f" снизошёл до меня). Я передам ваше соообщение кому-нибудь.")
        await cd.tg_bot.send_message(user_id,
                                     negative_reply_text)
        await cd.tg_bot.send_message(cd.TELEGRAM_SETTINGS.TG_MASTER_IDS[0],
                                     f"{message.from_user.username}: {message.md_text}")
    else:
        if not executor_exists(user_id):
            # loading full chat info for the first time
            chat_info: Chat = await cd.tg_bot.get_chat(chat_id)
        else:
            chat_info = message.chat
        group_ai = get_ai_executor_full(chat=chat_info)

        if cd.is_reply(message) or group_ai.should_react(message.html_text):
            user_text = await cd.preprocessor.process_tg_message(message,
                                                                 tg_bot=cd.tg_bot)
            if user_text is None:
                return None  # do not reply

            await cd.tg_bot.send_chat_action(message.chat.id, 'typing')
            reply_text = await group_ai.heed_and_reply(message=user_text,
                                                       author=f"{chat_id}_{message.from_user.username}")

            chunks = split_text_by_sentences(reply_text,
                                             cd.TELEGRAM_SETTINGS.TG_MAX_MESSAGE_LENGTH)
            for chunk in chunks:
                await message.reply(text=chunk)


def imported_ok():
    print('\t%-20s%-20s' % ("handlers:", 'private_message, group_message'))
