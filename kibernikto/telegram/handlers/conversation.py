import logging

from aiogram import Router, F, enums
from aiogram.filters import or_f
from aiogram.types import Message

from kibernikto.telegram.agent import telegram_agent as _agent_module
from kibernikto.telegram.utils.permissions import should_react

logger = logging.getLogger(__name__)

conversation_router = Router(name="conversation_router")


async def _process_and_reply(message: Message) -> None:
    """
    Delegate the whole "Telegram message → agent → Telegram reply" loop to
    the currently active :class:`TelegramAgent`.

    Looking the agent up via ``_agent_module`` (not the imported name) means
    that calls to :func:`set_telegram_agent` are picked up at runtime — the
    bot can be reconfigured with a subclass without restarting Python.
    """
    result = await _agent_module.kibernikto_telegram_agent.process_message(message)
    if result is None:
        return
    await _agent_module.kibernikto_telegram_agent.reply_to(message, result)


@conversation_router.message(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_private_message(message: Message):
    """Handle private messages with access control."""
    user_id = message.from_user.id
    logger.info(f"Processing private message from user {user_id}")

    await _process_and_reply(message)


@conversation_router.edited_message(F.chat.type == enums.ChatType.PRIVATE, ~F.text.startswith('/'),
                                    ~F.caption.startswith('/'))
async def handle_edited_message(message: Message):
    """Handle edited private messages."""
    user_id = message.from_user.id
    logger.info(f"Processing edited private message from user {user_id}: {message.md_text}")

    await _process_and_reply(message)


@conversation_router.message(or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP),
                             ~F.text.startswith('/'), ~F.caption.startswith('/'))
async def handle_group_message(message: Message):
    """Handle group messages, reacting only when addressed or replied to."""
    user_id = message.from_user.id
    logger.info(f"Processing group message from user {user_id}: {message.text} in {message.chat.title}")

    if not should_react(message):
        logger.debug(f"skipping message from {user_id} in {message.chat.title}")
        return

    await _process_and_reply(message)
