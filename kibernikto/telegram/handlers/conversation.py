import logging
from typing import Sequence

from aiogram import Router, F, enums
from aiogram.client import bot
from aiogram.filters import or_f
from aiogram.types import Message
from pydantic_ai import AgentRunResult, ImageUrl, BinaryImage
from pydantic_ai.messages import UserContent, ModelMessage

from kibernikto.ai.agent import kibernikto_agent
from kibernikto.ai.agent.core.history import history_storage
from kibernikto.telegram.utils.permissions import should_react
from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor

logger = logging.getLogger(__name__)

conversation_router = Router(name="conversation_router")


@conversation_router.message(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_private_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id
    message_preprocessor = TelegramMessagePreprocessor()
    user_message: str | Sequence[UserContent] = await message_preprocessor.process_tg_message(message)
    logger.info(f"Processing private message from user {user_id}: {user_message}")

    # Получаем историю сообщений для данного чата
    chat_history = history_storage.get_conversation(message.chat.id)

    result: AgentRunResult = await kibernikto_agent.run(user_message, message_history=chat_history)

    # Сохраняем новые сообщения в историю
    history_storage.add_messages(message.chat.id, result.new_messages())

    await message.answer(result.output)


@conversation_router.edited_message(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'),
                                    ~F.caption.startswith('/'))
async def handle_edited_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id
    logger.info(f"Processing edited private message from user {user_id}: {message.md_text}")

    chat_history = history_storage.get_conversation(message.chat.id)
    result = await kibernikto_agent.run(message.text, message_history=chat_history)
    history_storage.add_messages(message.chat.id, result.new_messages())
    await message.answer(result.data)


@conversation_router.message(or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP),
                             ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_group_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id
    logger.info(f"Processing group message from user {user_id}: {message.text} in {message.chat.title}")

    if should_react(message):
        chat_history = history_storage.get_conversation(message.chat.id)
        result = await kibernikto_agent.run(message.text, message_history=chat_history)
        history_storage.add_messages(message.chat.id, result.new_messages())
        await message.answer(result.data)
    else:
        logger.debug(f"skipping message from {user_id} in {message.chat.title}")
