# Utils, Runner & Logging

Reference for the framework-agnostic utilities (`kibernikto/utils/`), the runner / entry point
(`kibernikto/telegram/runner.py` and `kibernikto/cmd/__start.py`), the Telegram-side
helpers (`kibernikto/telegram/utils/`), and the Logfire-based logging setup.

## Entry Points

There are three ways to start the bot. All three converge on `runner.run_sync()`.

### 1. `kibernikto` CLI (PyPI install)

```toml
# pyproject.toml
[project.scripts]
kibernikto = "kibernikto.cmd.__start:start"
```

```bash
kibernikto --env_file_path=/path/to/kibernikto.env
```

The CLI does its own `load_dotenv(args.env_file_path)` and then calls
`configure_logger()` → `print_banner()` → `runner.run_sync()`.

### 2. `main.py` (this repo)

```python
# main.py
from kibernikto.cmd import start
if __name__ == '__main__':
    start(outer_env=True)
```

`outer_env=True` tells `__start.py` to **skip** `load_dotenv` — the host app (your code) is
responsible for env loading. This is what you want when embedding Kibernikto in a larger app where
env vars are managed by the host.

### 3. Programmatic (e.g. inside another async app)

```python
import asyncio
from kibernikto.config import configure_logger, print_banner
from kibernikto.telegram import runner

configure_logger()
print_banner()
asyncio.run(runner.run_async())
```

`runner.run_async()` exists alongside `runner.run_sync()` for embedding in an existing event loop.
It calls `init()` first (idempotent — raises `RuntimeError` if called twice) and then
`await tg_dispatcher.start_polling(tg_bot)`.

## `kibernikto.cmd.__start`

```python
# kibernikto/cmd/__start.py
import argparse
from dotenv import load_dotenv
from kibernikto.config import configure_logger, print_banner
from kibernikto.telegram import runner


def start(outer_env=False):
    parser = argparse.ArgumentParser(description='Run Kibernikto')
    parser.add_argument('--env_file_path', metavar='env_file_path', required=False,
                        help='env file location', default='.env')
    args = parser.parse_args()

    if not outer_env:
        load_dotenv(dotenv_path=args.env_file_path)

    configure_logger()
    print_banner()
    runner.run_sync()


if __name__ == '__main__':
    start()
```

Only one flag (`--env_file_path`). The default is `.env` relative to the working directory. There
is no `--port`, no `--webhook`, no `--debug`. Polling is the only mode.

## `kibernikto.telegram.runner`

```python
# kibernikto/telegram/runner.py
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
    global tg_bot, tg_dispatcher
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
```

### Module-level state

| Global | Set in | Used by |
|---|---|---|
| `tg_bot` | `init()` | The `Bot` instance passed to polling |
| `bot_me` | `on_startup()` | `permissions.should_react` reads `bot_me.full_name` and `bot_me.username` to add the bot's display name to the reaction triggers |
| `tg_dispatcher` | `init()` | The aiogram `Dispatcher` |

`bot_me` is only populated **after** the startup hook runs, so any code that needs the bot's
`@username` (e.g. group reaction triggers) must wait until the first update is processed.

### `init()` is not idempotent across processes

`init()` raises `RuntimeError` on the second call within the same Python process. If you need to
restart the bot in the same process (e.g. tests), reset the globals manually:

```python
import kibernikto.telegram.runner as r
r.tg_bot = None
r.tg_dispatcher = None
r.bot_me = None
```

### `parse_mode=ParseMode.HTML`

The bot is configured with HTML parse mode, so you can use `<b>`, `<i>`, `<code>`, etc. directly
in `message.answer(...)` calls. Markdown formatting is **not** the default — see the Markdown
helpers in `kibernikto/utils/text.py` for the `prepare_for_MARKDOWN` path used by the
`conversation.reply` utility.

## Telegram Utils

### `kibernikto/telegram/utils/conversation.py`

```python
async def send_random_sticker(chat_id: int, sticker_list: List[str], bot: Bot):
    sticker_id = choice(sticker_list)
    await bot.send_sticker(sticker=sticker_id, chat_id=chat_id)


def is_reply(message: Message):
    return bool(
        message.reply_to_message
        and message.reply_to_message.from_user.id == message.bot.id
    )


def get_message_text(message: Message):
    return message.text or message.caption or message.html_text or message.md_text


async def reply(
        message: Message,
        reply_text: str,
        file_attachment: Optional[FSInputFile] = None,
        image_attachment: Optional[FSInputFile] = None,
) -> str:
    if not file_attachment and not image_attachment:
        await _text_reply(message=message, reply_text=reply_text)
        return reply_text
    caption = clear_text_format(reply_text[:MAX_CAPTION_LENGTH])
    if file_attachment:
        await message.reply_document(document=file_attachment, caption=caption)
    if image_attachment:
        await message.reply_photo(photo=image_attachment, caption=caption)
    return caption


async def _text_reply(message: Message, reply_text: str) -> None:
    chunks = split_text_by_sentences(reply_text, MAX_MESSAGE_LENGTH)
    for chunk in chunks:
        try:
            await message.reply(text=prepare_for_MARKDOWN(chunk), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error sending formatted message: {e}")
            logger.debug(f"Problematic chunk: {chunk}")
            await message.reply(text=clear_text_format(chunk))
```

- `is_reply(message)` — `True` if the message is a reply **to the bot**. Used by `should_react` for
  group reactions.
- `get_message_text(message)` — tries `text` → `caption` → `html_text` → `md_text`. Returns
  falsy on empty.
- `reply(message, reply_text, file_attachment=, image_attachment=)` — high-level helper that
  splits long text into chunks (sentence-based) and falls back to plain text if Markdown parse
  fails. Use this from custom handlers instead of `message.answer(...)` when the response might
  exceed 4096 characters.
- `MAX_MESSAGE_LENGTH = 4096` and `MAX_CAPTION_LENGTH = 1023` are module-level constants
  duplicating `TG_MAX_MESSAGE_LENGTH` / `TG_MAX_CAPTION_LENGTH`.

### `kibernikto/telegram/utils/permissions.py`

```python
def is_from_admin(message):
    return (
        message.from_user.id == TELEGRAM_SETTINGS.MASTER_ID
        or message.from_user.id in TELEGRAM_SETTINGS.MASTER_IDS
    )


def admin_or_public(message):
    return is_from_admin(message) or is_public()


def is_public() -> bool:
    return TELEGRAM_SETTINGS.PUBLIC


def group_allowed(message):
    if not TELEGRAM_SETTINGS.FRIEND_GROUP_IDS:
        return True
    return message.chat.id in TELEGRAM_SETTINGS.FRIEND_GROUP_IDS


def should_react(message: Message):
    from kibernikto.telegram.runner import bot_me
    from telegram.utils.conversation import is_reply, get_message_text  # ⚠️ wrong import
    calls: List[str] = [] + TELEGRAM_SETTINGS.REACTION_CALLS
    calls.append(bot_me.full_name)
    calls.append(f"@{bot_me.username}")
    message_text = get_message_text(message)
    if not message_text:
        return False
    call_to_react = any(word.lower() in message_text.lower() for word in calls)
    return is_reply(message) or call_to_react
```

> ⚠️ **The `from telegram.utils.conversation import ...` import is broken.** It should be
> `from kibernikto.telegram.utils.conversation import ...`. The default `REACTION_CALLS`
> (`['honda', 'киберникто']`) doesn't exercise the broken path for keyword matching, but a reply in
> a group raises `ModuleNotFoundError`. See [Common Gotchas](../SKILL.md#common-gotchas) in the
> main SKILL.md.

## Framework-Agnostic Utils

### `kibernikto/utils/text.py`

A grab-bag of text helpers used by the Telegram reply path and by user code:

| Function | Purpose |
|---|---|
| `split_text(text, length=4096)` | Hard-character chunking |
| `split_text_by_sentences(text, max_length)` | Sentence-aware chunking, used by `_text_reply` |
| `split_text_into_chunks_by_sentences(text, sentences_per_chunk=2)` | Group every N sentences |
| `remove_text_in_brackets_and_parentheses(text)` | Strip `(...)` and `[...]` |
| `clear_text_format(text)` | Collapse `  `→` `, strip `....` and `**`/`*` |
| `prepare_for_MARKDOWN(text)` | Convert `**`→`*`, escape `_` |
| `prepare_for_MARKDOWN_V2(text)` | Convert `**`→`*` (no escape) |
| `text_to_html(text)` | `**bold**` → `<b>bold</b>` |
| `parse_json_garbage(s, start="{")` | Best-effort `json.loads` of model output with stray prefixes |
| `get_website_html(url)` | aiohttp GET |
| `get_website_as_text(url)` | aiohttp GET via toolsyep's reader (third-party, flaky) |

The `parse_json_garbage` helper is useful when a model returns ``"Here you go: {...}"`` and you need
to extract the JSON object.

### `kibernikto/utils/image.py`

```python
URL = 'https://api.imgbb.com/1/upload'
IMAGE_STORAGE_API_KEY = os.environ.get('IMAGE_STORAGE_API_KEY', "d581d52610fc664c1d632cbeb8362686")


async def publish_image_file(image_bytes, name):
    try:
        url = "https://api.imgbb.com/1/upload"
        payload = {'key': IMAGE_STORAGE_API_KEY, 'image': image_bytes, 'name': name, 'expiration': '300'}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload) as response:
                resp = await response.json()
                if response.status == 200:
                    return resp['data']['url']
                else:
                    logging.error(f"Image upload failed: {resp}")
                    return None
    except Exception as e:
        logging.error(f"Image upload failed: {str(e)}")
        return None
```

The hard-coded fallback key in the source is for **demo** use. Set `IMAGE_STORAGE_API_KEY` in your
env to your own imgbb key. The `'expiration': '300'` (5 minutes) means imgbb deletes the image
after 5 minutes — fine for one-shot LLM vision, not for hosted images.

There's also an unused legacy `post(filename, name)` helper that takes a file path. The current
preprocessor uses `publish_image_file(image_bytes, name)` exclusively.

### `kibernikto/utils/timer.py`

Currently a stub — the file exists but the public surface is empty. Used by historical logging
timers; safe to ignore unless you start adding timing utilities.

## Logging Setup

`kibernikto/config.py`:

```python
def configure_logger():
    formatter = logging.Formatter(
        fmt='%(levelname)-8s %(asctime)s %(name)s:%(filename)s:%(lineno)d %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S',
    )
    logfire.configure(service_name=APP_SETTINGS.INSTANCE_NAME, send_to_logfire='if-token-present')
    logfire.instrument_pydantic_ai()
    logfire_handler = logfire.LogfireLoggingHandler()
    logfire_handler.setFormatter(formatter)
    logging.basicConfig(
        format=formatter._fmt,
        datefmt=formatter.datefmt,
        level=logging.WARN,
        handlers=[logfire_handler],
    )
    logging.getLogger('kibernikto').setLevel(logging.DEBUG)
    logging.getLogger('aiogram').setLevel(logging.INFO)
    logging.getLogger('pydantic_ai').setLevel(logging.INFO)
```

### Behaviour

1. **Logfire** is configured with `service_name=APP_INSTANCE_NAME` and `send_to_logfire='if-token-present'`
   — if `LOGFIRE_TOKEN` is set, traces and logs go to Logfire; otherwise everything stays local.
2. `logfire.instrument_pydantic_ai()` instruments every pydantic-ai model call. To see token usage
   per request, open the Logfire dashboard.
3. `logging.basicConfig` uses the Logfire handler. Setting `level=logging.WARN` for the root logger
   and then explicitly bumping `kibernikto` to `DEBUG` and `aiogram`/`pydantic_ai` to `INFO` is the
   intended policy — quiet by default, verbose in the framework's own modules.
4. The `logfire_handler.setFormatter(formatter)` call is followed by a comment `# FIXME: does not
   work` in the source — Logfire's handler ignores the formatter and applies its own JSON format.
   Don't rely on the formatter being applied to Logfire output.

### Customising the logger

To add a new module-specific logger:

```python
import logging
logger = logging.getLogger('kibernikto.my_module')
logger.setLevel(logging.INFO)
```

The root logger accepts records from any module — Kibernikto's own loggers follow the
`kibernikto.*` naming convention. Use `logging.getLogger(__name__)` (which expands to
`kibernikto.telegram.handlers.conversation` for the conversation module) and you'll inherit the
`DEBUG` level from `kibernikto` automatically.

## Adding a Custom CLI Flag

If you need `--debug`, `--webhook`, or similar:

1. Modify `kibernikto/cmd/__start.py` — add an `argparse` argument.
2. Add a corresponding setting to `AppSettings` if it should be env-driven too.
3. Update the `start()` function body to honour the flag.

The framework ships with one flag (`--env_file_path`) for a reason — adding CLI flags means
maintaining both env-var and command-line code paths. Prefer env vars for everything that doesn't
change between runs.
