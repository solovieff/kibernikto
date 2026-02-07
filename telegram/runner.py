from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import User

from kibernikto.config import APP_SETTINGS
from kibernikto.telegram.config import TELEGRAM_SETTINGS, print_banner
from kibernikto.telegram.utils.conversation import send_random_sticker
from kibernikto.telegram.handlers import conversation_router, commands_router
from kibernikto.telegram.middleware.middleware_firewall import FirewallMiddleware
from kibernikto.telegram.middleware.middleware_service import ServiceMiddleware, ErrorsMiddleware
from kibernikto.telegram.middleware.middleware_subscription import SubscriptionMiddleware

tg_bot: Bot | None = None
bot_me: User | None = None
tg_dispatcher: Dispatcher | None = None


def init():
    global tg_bot
    global tg_dispatcher

    if tg_bot is not None:
        raise RuntimeError('Bot already initialized')

    print_banner()

    tg_bot = Bot(token=TELEGRAM_SETTINGS.BOT_KEY,
                 default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    tg_dispatcher = Dispatcher(name=APP_SETTINGS.INSTANCE_NAME)
    tg_dispatcher.startup.register(on_startup)

    middlewares = [ServiceMiddleware, ErrorsMiddleware, FirewallMiddleware, SubscriptionMiddleware]
    for middleware in middlewares:
        middleware.apply_if_needed(tg_dispatcher)
    tg_dispatcher.include_router(commands_router)
    tg_dispatcher.include_router(conversation_router)


def run_sync():
    init()
    tg_dispatcher.run_polling(tg_bot)


async def run_async():
    init()
    await tg_dispatcher.start_polling(tg_bot)


async def on_startup(bot: Bot):
    global bot_me
    bot_me = await tg_bot.get_me()

    if TELEGRAM_SETTINGS.SAY_HI:
        master_id = TELEGRAM_SETTINGS.MASTER_ID
        await send_random_sticker(chat_id=master_id, sticker_list=TELEGRAM_SETTINGS.STICKER_IDS, bot=bot)
