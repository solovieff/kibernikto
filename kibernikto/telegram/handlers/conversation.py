import logging

from aiogram import Router, F
from aiogram.filters import or_f
from aiogram import enums
from aiogram.types import Message

logger = logging.getLogger(__name__)

conversation_router = Router(name="conversation_router")


@conversation_router.message(F.chat.type == "private", ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_private_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id
    logger.info(f"Processing private message from user {user_id}: {message.text}")

    # TODO: Integrate with AI agent for response generation
    await message.answer("Private message received. AI integration pending.")

@conversation_router.edited_message(F.chat.type == "private", ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_edited_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id
    logger.info(f"Processing edited private message from user {user_id}: {message.md_text}")

    # TODO: Integrate with AI agent for response generation
    await message.answer("Private edited message received. AI integration pending.")


@conversation_router.message(or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP))
async def handle_group_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id
    logger.info(f"Processing group message from user {user_id}: {message.text}")

    # TODO: Integrate with AI agent for response generation
    await message.answer("Group message received. AI integration pending.")
