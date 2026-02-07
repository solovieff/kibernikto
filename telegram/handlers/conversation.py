import logging

from aiogram import Router, F, enums
from aiogram.filters import or_f
from aiogram.types import Message
from pydantic_ai import AgentRunResult

from kibernikto.ai.agent.kibernikto.kibernikto_agent import agent
from kibernikto.telegram.utils.permissions import should_react

logger = logging.getLogger(__name__)

conversation_router = Router(name="conversation_router")


@conversation_router.message(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_private_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id

    logger.info(f"Processing private message from user {user_id}: {message.text}")

    result: AgentRunResult = await agent.run(message.text)
    await message.answer(result.output)


@conversation_router.edited_message(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'),
                                    ~F.caption.startswith('/'))
async def handle_edited_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id
    logger.info(f"Processing edited private message from user {user_id}: {message.md_text}")

    result = await agent.run(message.text)
    await message.answer(result.data)


@conversation_router.message(or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP),
                             ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_group_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id
    logger.info(f"Processing group message from user {user_id}: {message.text} in {message.chat.title}")

    if should_react(message):
        result = await agent.run(message.text)
        await message.answer(result.data)
    else:
        logger.debug(f"skipping message from {user_id} in {message.chat.title}")
