import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import StarTransaction, TransactionPartnerUser, LabeledPrice

DEFAULT_SUBSCRIPTION_PERIOD = 2592000
SUBSCRIPTION_PAYLOAD = 'subscription_payload'
TRANSACTION_PAGE_SIZE = 100
logger = logging.getLogger(__name__)


async def create_payment_link(bot: Bot, price: int = 1,
                              descr: str = 'Make a symbolic payment to enjoy my power!') -> str:
    if type(price) is not int or not 1 <= price <= 10000:
        raise ValueError('Subscription price must be 1–10000 Stars')
    payment_link = await bot.create_invoice_link(title="Kibernikto",
                                                 description=descr,
                                                 payload=SUBSCRIPTION_PAYLOAD,
                                                 currency='XTR',
                                                 prices=[LabeledPrice(label="Subscription", amount=price)],
                                                 provider_token='',
                                                 subscription_period=DEFAULT_SUBSCRIPTION_PERIOD, )
    return payment_link


async def check_sub(user_id: int, bot: Bot) -> bool:
    """Find a non-refunded subscription payment across all Telegram pages."""
    offset = 0
    payments: list[StarTransaction] = []
    refunds: set[str] = set()
    while True:
        page = await bot.get_star_transactions(offset=offset, limit=TRANSACTION_PAGE_SIZE)
        for transaction in page.transactions:
            if isinstance(transaction.receiver, TransactionPartnerUser) and transaction.receiver.user.id == user_id:
                refunds.add(transaction.id)
            source = transaction.source
            if not isinstance(source, TransactionPartnerUser) or source.user.id != user_id:
                continue
            if (source.transaction_type == 'invoice_payment'
                    and source.invoice_payload == SUBSCRIPTION_PAYLOAD
                    and source.subscription_period == DEFAULT_SUBSCRIPTION_PERIOD
                    and transaction.amount > 0):
                payments.append(transaction)
        if len(page.transactions) < TRANSACTION_PAGE_SIZE:
            break
        offset += len(page.transactions)

    last_payment = max((payment for payment in payments if payment.id not in refunds),
                       key=lambda payment: payment.date, default=None)
    if last_payment is None:
        logger.debug('No subscription payment for user %s', user_id)
        return False
    age = (datetime.now(last_payment.date.tzinfo) - last_payment.date).total_seconds()
    return 0 <= age < DEFAULT_SUBSCRIPTION_PERIOD
