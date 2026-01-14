from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import User

from kibernikto.config import APP_SETTINGS
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.middleware import middleware_auth, middleware_service, middleware_subscription
from kibernikto.telegram.utils.conversation import send_random_sticker

tg_bot: Bot | None = None
bot_me: User | None = None
tg_dispatcher: Dispatcher | None = None


def init():
    global tg_bot
    global tg_dispatcher

    tg_bot = Bot(token=TELEGRAM_SETTINGS.TG_BOT_KEY,
                 default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    tg_dispatcher = Dispatcher(name=APP_SETTINGS.INSTANCE_NAME)
    tg_dispatcher.startup.register(on_startup)

    middleware_service.apply_if_needed(tg_dispatcher)
    middleware_auth.apply_if_needed(tg_dispatcher)
    middleware_subscription.apply_if_needed(tg_dispatcher)


def run_sync():
    init()
    tg_dispatcher.run_polling(tg_bot)


async def run_async():
    init()
    await tg_dispatcher.start_polling(tg_bot)


async def on_startup(bot: Bot):
    if TELEGRAM_SETTINGS.TG_SAY_HI:
        master_id = TELEGRAM_SETTINGS.TG_MASTER_ID
        await send_random_sticker(chat_id=master_id, sticker_list=TELEGRAM_SETTINGS.STICKER_IDS, bot=bot)
