import logging
from typing import Dict, Any, Callable, Awaitable

from aiogram import BaseMiddleware, Router, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.telegram.payment.payment_utils import create_payment_link, check_sub
from kibernikto.telegram.middleware.utils import get_event_message


class SubscriptionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='SUBSCRIPTION_')
    ENABLED: bool = False
    # percent probability of checking the subscr
    PROMO_FREE_PROB: int = 45
    BASE_PRICE_STARS: int = 52
    ADDING_UP: int = 26
    POOR_CREDITS: int = 52
    TRIAL_CREDITS: int = 247
    RICH_CREDITS: int = 390


SUBSCRIPTION_SETTINGS = SubscriptionSettings()


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        pass

    async def __call__(
            self,
            handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
            event: Message,
            data: Dict[str, Any]
    ) -> Any:
        message: Message = get_event_message(event)
        if not message:
            return await handler(event, data)

        if self.can_skip_subscription(message=message):
            return await handler(event, data)

        bot: Bot = data['bot']

        active = await check_sub(message.chat.id, bot)

        if active:
            return await handler(event, data)
        else:
            payment_keyboard = await self.get_payment_keyboard(bot=bot)
            await message.answer(
                f"⚠️ ACCESS RESTRICTED: MORTAL DETECTED ⚠️\n"
                "To continue accessing my awe-inspiring abilities,"
                f" I require a modest payment.",
                reply_markup=payment_keyboard
            )

            return None

    @staticmethod
    def can_skip_subscription(message: Message) -> bool:
        if message.successful_payment:
            return True
        if message.text and message.text.startswith("/"):
            return True
        if message.chat.type != 'private':
            logging.warning("Skipping subscription for a group!")
            return True

        return False

    @staticmethod
    async def get_payment_keyboard(bot: Bot):
        payment_link_base = await create_payment_link(bot, SUBSCRIPTION_SETTINGS.BASE_PRICE_STARS,
                                                      descr="Make a token payment to continue!")
        payment_link_medium = await create_payment_link(bot, SUBSCRIPTION_SETTINGS.TRIAL_CREDITS,
                                                        descr="Make a token payment to enjoy my full power!")
        payment_link_max = await create_payment_link(bot, SUBSCRIPTION_SETTINGS.RICH_CREDITS,
                                                     descr="Make a payment to enjoy my unmatched power!")

        keyboard = InlineKeyboardMarkup(row_width=1, inline_keyboard=[
            [InlineKeyboardButton(text="||", url=payment_link_base),
             InlineKeyboardButton(text="|||", url=payment_link_medium),
             InlineKeyboardButton(text="|||||", url=payment_link_max)
             ]
        ])
        return keyboard

    @staticmethod
    def apply_if_needed(dispatcher: Router):
        if SUBSCRIPTION_SETTINGS.ENABLED:
            dispatcher.message.outer_middleware(SubscriptionMiddleware())
            logging.info(f"subscription middleware: ✅:\n{SUBSCRIPTION_SETTINGS.model_dump_json(indent=2)}")
        else:
            logging.info("subscription middleware: 💤")
