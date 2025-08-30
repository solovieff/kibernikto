import logging
import random
from typing import Dict, Any

from aiogram.types import Update, InlineKeyboardMarkup, InlineKeyboardButton
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.telegram.payment.payments import create_payment_link, check_sub
from kibernikto.utils.telegram import timer
from kibernikto.telegram import get_ai_executor


class SubscriptionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='SUBSCRIPTION_')
    # percent probability of checking the subscr
    PROMO_FREE_PROB: int = 45
    BASE_PRICE_STARS: int = 52
    ADDING_UP: int = 26
    ENABLED: bool = False
    POOR_CREDITS: int = 52
    TRIAL_CREDITS: int = 247
    RICH_CREDITS: int = 390


P_SETTINGS = SubscriptionSettings()

if P_SETTINGS.ENABLED:
    from avatar.telegram import avatar_dispatcher


    @avatar_dispatcher.dp.update.outer_middleware()
    async def subscription_middleware(handler, event: Update, data: Dict[str, Any]) -> Any:

        if event.message:
            if event.message.successful_payment:
                return await handler(event, data)
            chat_id = event.message.chat.id
        else:
            return await handler(event, data)

        # if is_from_admin(event.message, check_bot_admin=False):
        #    return await handler(event, data)

        existing_executor = get_ai_executor(chat_id)

        # new users can talk
        if not existing_executor or (event.message.text and event.message.text.startswith("/")):
            need_to_check_subscription = False
        elif event.message.chat.type != 'private':
            logging.warning("Skipping subscription for a group!")
            need_to_check_subscription = False
        else:
            # if already talked a bit: starting to fuck their brains with a payment
            if len(existing_executor.messages) >= 2:
                need_to_check_subscription = random.random() * 100 > P_SETTINGS.PROMO_FREE_PROB
            else:
                need_to_check_subscription = False

        if not need_to_check_subscription:
            return await handler(event, data)

        bot = data['bot']
        with timer("Subscription check"):
            active = await check_sub(chat_id, bot)

        if active:
            return await handler(event, data)
        else:
            payment_link_base = await create_payment_link(bot, P_SETTINGS.BASE_PRICE_STARS,
                                                          descr="Make a token payment to continue!")
            payment_link_medium = await create_payment_link(bot, P_SETTINGS.TRIAL_CREDITS,
                                                            descr="Make a token payment to enjoy my full power!")
            payment_link_max = await create_payment_link(bot, P_SETTINGS.RICH_CREDITS,
                                                         descr="Make a payment to enjoy my unmatched power!")

            keyboard = InlineKeyboardMarkup(row_width=1, inline_keyboard=[
                [InlineKeyboardButton(text="||", url=payment_link_base),
                 InlineKeyboardButton(text="|||", url=payment_link_medium),
                 InlineKeyboardButton(text="|||||", url=payment_link_max)
                 ]
            ])

            await event.message.answer(
                f"⚠️ ACCESS RESTRICTED: MORTAL DETECTED ⚠️\n"
                "To continue accessing my awe-inspiring abilities,"
                f" I require a modest payment in ⭐.",
                reply_markup=keyboard
            )

            return None
else:
    print('\t%-20s%-20s' % ("payments:", 'disabled'))
