"""Stars checkout validation and payment acknowledgements, without model calls."""

import logging

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery

from kibernikto.telegram.middleware.middleware_subscription import SUBSCRIPTION_SETTINGS
from kibernikto.telegram.payment.payment_utils import SUBSCRIPTION_PAYLOAD

logger = logging.getLogger(__name__)
payments_router = Router(name='payments_router')


@payments_router.pre_checkout_query()
async def handle_pre_checkout(query: PreCheckoutQuery) -> None:
    settings = SUBSCRIPTION_SETTINGS
    prices = {settings.BASE_PRICE_STARS, settings.TRIAL_CREDITS, settings.RICH_CREDITS}
    valid = (settings.ENABLED and query.currency == 'XTR'
             and query.invoice_payload == SUBSCRIPTION_PAYLOAD
             and 1 <= query.total_amount <= 10000 and query.total_amount in prices)
    if not valid:
        await query.answer(ok=False, error_message='This subscription invoice is not available. Request a new link.')
        return
    await query.answer(ok=True)


@payments_router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    if payment is None:
        return
    if payment.currency != 'XTR' or payment.invoice_payload != SUBSCRIPTION_PAYLOAD:
        logger.warning('Unexpected successful payment in chat %s', message.chat.id)
        return
    logger.info('Subscription payment received in chat %s: %s Stars', message.chat.id, payment.total_amount)
    # Entitlement is checked against Telegram transactions, not an in-memory credit top-up.
    await message.answer('Payment received. Thank you! Your subscription payment will be checked with Telegram.')