"""/reset: wipe the chat's history and the bot's notes about it (credits stay), after an inline confirmation."""

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import kibernikto.telegram.bridge as _bridge_module
from kibernikto.storage.chat_wipe import wipe_chat
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.utils.permissions import is_admin_id

logger = logging.getLogger(__name__)
reset_router = Router(name='reset_router')

CONFIRM, CANCEL = 'reset:yes', 'reset:no'
_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text='🗑 Erase', callback_data=CONFIRM),
    InlineKeyboardButton(text='Cancel', callback_data=CANCEL),
]])


def _may_reset(chat_type: str, user_id: int) -> bool:
    """Private chats belong to their user; groups are admin-only."""
    if chat_type == ChatType.PRIVATE:
        return True
    return TELEGRAM_SETTINGS.ADMIN_COMMANDS_ALLOWED and is_admin_id(user_id)


@reset_router.message(Command('reset'))
async def cmd_reset(message: Message) -> None:
    if message.from_user is None or not _may_reset(message.chat.type, message.from_user.id):
        await message.answer('Only admins can reset a group chat.')
        return
    await message.answer(
        "Erase this chat's history and my notes about it? Credits stay. This cannot be undone.",
        reply_markup=_KEYBOARD,
    )


@reset_router.callback_query(F.data.in_({CONFIRM, CANCEL}))
async def handle_reset_choice(query: CallbackQuery) -> None:
    prompt = query.message
    if not isinstance(prompt, Message):  # Telegram no longer serves the original message.
        await query.answer('This request expired. Send /reset again.', show_alert=True)
        return
    if not _may_reset(prompt.chat.type, query.from_user.id):
        await query.answer('Only admins can do that.', show_alert=True)
        return
    if query.data == CANCEL:
        await prompt.edit_text('Cancelled.')
        await query.answer()
        return
    bridge = _bridge_module.get_telegram_bridge()
    notes = await wipe_chat(str(prompt.chat.id), history=bridge.history_storage, agent_name=bridge.agent.name)
    logger.info('User %s reset chat %s (%d note files)', query.from_user.id, prompt.chat.id, notes)
    await prompt.edit_text('✅ History and notes erased.')
    await query.answer()
