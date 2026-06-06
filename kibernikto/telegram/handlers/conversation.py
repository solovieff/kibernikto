import logging

from aiogram import Router, F, enums
from aiogram.filters import or_f
from aiogram.types import Message

from kibernikto.telegram.agent import telegram_agent as _agent_module
from kibernikto.telegram.utils.permissions import should_react

logger = logging.getLogger(__name__)

conversation_router = Router(name="conversation_router")


async def _process_and_reply(message: Message) -> None:
    """Run the active agent on ``message`` and send its reply.

    The agent is resolved via ``_agent_module`` (not the imported name) so
    that :func:`set_telegram_agent` is honoured at runtime without a restart.
    A single "typing…" action is shown; Telegram keeps it up until the answer
    arrives, so there is no need to refresh it on a loop.
    """
    agent = _agent_module.kibernikto_telegram_agent

    await message.bot.send_chat_action(message.chat.id, "typing")
    result = await agent.process_message(message)
    await agent.reply_to(message, result)


@conversation_router.message(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_private_message(message: Message):
    """Handle private messages."""
    logger.info(f"Processing private message from user {message.from_user.id}")
    await _process_and_reply(message)


@conversation_router.edited_message(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'),
                                    ~F.caption.startswith('/'))
async def handle_edited_message(message: Message):
    """Handle edited private messages."""
    logger.info(f"Processing edited private message from user {message.from_user.id}: {message.md_text}")
    await _process_and_reply(message)


@conversation_router.message(or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP),
                             ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_group_message(message: Message):
    """Handle group messages, reacting only when addressed or replied to."""
    if not should_react(message):
        logger.debug(f"skipping message from {message.from_user.id} in {message.chat.title}")
        return

    logger.info(f"Processing group message from user {message.from_user.id} in {message.chat.title}")
    await _process_and_reply(message)
