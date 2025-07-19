from aiogram.types import Message, Chat

from kibernikto.telegram import executor_exists, get_ai_executor_full


async def get_ready_executor(message: Message, hide_errors: bool = True):
    """

    :param message: telegram message
    :param hide_errors: if the errors should be processed in Kibernikto superclass or sent to the top
    :return:
    """
    chat_id = message.chat.id

    if not executor_exists(chat_id):
        chat_info: Chat = await message.bot.get_chat(chat_id)
    else:
        chat_info = message.chat
    user_ai = get_ai_executor_full(chat=chat_info, user=message.from_user,
                                   hide_errors=hide_errors)
    return user_ai
