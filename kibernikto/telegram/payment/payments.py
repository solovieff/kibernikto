from datetime import datetime, timedelta
from typing import List

from aiogram import Bot
from aiogram.types import StarTransaction

DEFAULT_SUBSCRIPTION_PERIOD = 2592000


async def create_payment_link(bot: Bot, price=1,
                              descr='Make a symbolic payment to enjoy my power!') -> str:
    payment_link = await bot.create_invoice_link(title="Kibernikto",
                                                 description=descr,
                                                 payload='subscription_payload',
                                                 currency='XTR',
                                                 prices=[{"label": "Subscription: 30 days", "amount": price}],
                                                 provider_token='',
                                                 subscription_period=DEFAULT_SUBSCRIPTION_PERIOD, )
    return payment_link


async def check_sub(user_id, bot: Bot):
    data = await bot.get_star_transactions()
    transactions: List[StarTransaction] = data.transactions
    last_transaction = max(
        (transaction for transaction in transactions
         if
         transaction.source is not None and transaction.source.user.id == user_id and transaction.source.subscription_period == DEFAULT_SUBSCRIPTION_PERIOD),
        key=lambda t: t.date,
        default=None
    )
    # Check subscription status
    if last_transaction:
        transaction_date = last_transaction.date
        now = datetime.now(transaction_date.tzinfo)  # Current time with respect to the time zone
        time_since_transaction = now - transaction_date

        if time_since_transaction.total_seconds() <= DEFAULT_SUBSCRIPTION_PERIOD:
            # Subscription is active
            remaining_time = timedelta(seconds=DEFAULT_SUBSCRIPTION_PERIOD) - time_since_transaction
            remaining_days = remaining_time.days
            return True
        else:
            print(f"Subscription is not active for {user_id}")
            return False
    else:
        print("Subscription is not active.")
        return False
