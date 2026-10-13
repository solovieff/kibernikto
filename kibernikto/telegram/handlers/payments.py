"""Stars checkout: /pay top-ups, /balance, checkout validation and credit crediting (1 Star = 1 credit)."""

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

from kibernikto.storage.singletons import chat_data
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.utils.permissions import is_from_admin
from kibernikto.telegram.middleware.middleware_subscription import SUBSCRIPTION_SETTINGS
from kibernikto.telegram.payment.payment_utils import MAX_STARS, SUBSCRIPTION_PAYLOAD, TOPUP_PAYLOAD

logger = logging.getLogger(__name__)
payments_router = Router(name='payments_router')


def _subscription_price_valid(amount: int) -> bool:
    s = SUBSCRIPTION_SETTINGS
    return s.ENABLED and amount in {s.BASE_PRICE_STARS, s.TRIAL_CREDITS, s.RICH_CREDITS}


def _is_admin(message: Message) -> bool:
    return TELEGRAM_SETTINGS.ADMIN_COMMANDS_ALLOWED and message.from_user is not None and is_from_admin(message)


def _parse_int(raw: str) -> int | None:
    return int(raw) if raw.removeprefix('-').isdigit() else None


def _parse_stars(raw: str | None) -> int | None:
    """None → default top-up; N → N Stars; None when N is not 1..MAX_STARS."""
    if raw is None:
        return SUBSCRIPTION_SETTINGS.TOPUP_STARS
    stars = _parse_int(raw)
    return stars if stars is not None and 1 <= stars <= MAX_STARS else None


async def _admin_grant(message: Message, amount_raw: str, target_raw: str) -> None:
    """`/pay ±N tg_id` from admin: adjust a chat balance directly, no invoice."""
    delta, target = _parse_int(amount_raw), _parse_int(target_raw)
    if delta is None or target is None or delta == 0:
        await message.answer('Usage: /pay <±credits> <tg_id>. Example: /pay 100 123456789')
        return
    info = await chat_data.load(target)
    balance = info.adjust_credits(delta)
    await chat_data.save(target, info)
    logger.info('Admin %s adjusted chat %s by %+d credits, balance %s', message.from_user.id, target, delta, balance)
    await message.answer(f'✅ Chat {target}: {delta:+d} credits. Balance: {balance}.')


@payments_router.message(Command('pay'))
async def cmd_pay(message: Message, command: CommandObject) -> None:
    args = (command.args or '').split()
    if len(args) >= 2:
        if not _is_admin(message):
            await message.answer('Only admins can top up other users.')
            return
        await _admin_grant(message, args[0], args[1])
        return
    if message.chat.type != 'private':
        await message.answer('Top-ups work in a private chat with me only.')
        return
    stars = _parse_stars(args[0] if args else None)
    if stars is None:
        await message.answer(f'Usage: /pay [stars], 1–{MAX_STARS}. Example: /pay {SUBSCRIPTION_SETTINGS.TOPUP_STARS}')
        return
    await message.answer_invoice(
        title='Kibernikto credits',
        description=f'{stars} credits for my work. 1 ⭐ = 1 credit.',
        payload=TOPUP_PAYLOAD,
        currency='XTR',
        prices=[LabeledPrice(label='Credits', amount=stars)],
        provider_token='',
    )


@payments_router.message(Command('balance'))
async def cmd_balance(message: Message, command: CommandObject) -> None:
    args = (command.args or '').split()
    if not args:
        info = await chat_data.load(message.chat.id)
        await message.answer(f'💳 Balance: {info.credits} credits. Top up: /pay [stars]')
        return
    if not _is_admin(message):
        await message.answer('Only admins can check other users.')
        return
    target = _parse_int(args[0])
    if target is None:
        await message.answer('Usage: /balance [tg_id]')
        return
    info = await chat_data.load(target)
    await message.answer(f'💳 Chat {target}: {info.credits} credits.')


@payments_router.pre_checkout_query()
async def handle_pre_checkout(query: PreCheckoutQuery) -> None:
    amount_ok = query.currency == 'XTR' and 1 <= query.total_amount <= MAX_STARS
    match query.invoice_payload:
        case p if p == TOPUP_PAYLOAD:
            valid = amount_ok
        case p if p == SUBSCRIPTION_PAYLOAD:
            valid = amount_ok and _subscription_price_valid(query.total_amount)
        case _:
            valid = False
    if not valid:
        await query.answer(ok=False, error_message='This invoice is not available. Request a new one with /pay.')
        return
    await query.answer(ok=True)


@payments_router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    if payment is None:
        return
    if payment.currency != 'XTR' or payment.invoice_payload not in (SUBSCRIPTION_PAYLOAD, TOPUP_PAYLOAD):
        logger.warning('Unexpected successful payment in chat %s', message.chat.id)
        return
    # Credits live in the shared per-chat bucket; subscription renewals top up too, as in the old bot.
    chat_id = message.chat.id
    info = await chat_data.load(chat_id)
    info.add_credits(payment.total_amount)
    await chat_data.save(chat_id, info)
    logger.info('Payment %s in chat %s: +%s credits, balance %s',
                payment.invoice_payload, chat_id, payment.total_amount, info.credits)
    await message.answer(f'⭐ Payment received: +{payment.total_amount} credits. Balance: {info.credits}. Thank you!')