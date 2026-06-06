# Telegram Handlers

The Telegram dispatcher registers two routers and a set of middlewares. This reference covers the
routers (the `kibernikto/telegram/handlers/` package) and how they delegate to the core agent.

## Router Layout

```python
# kibernikto/telegram/runner.py
from kibernikto.telegram.handlers import conversation_router, commands_router

tg_dispatcher.include_router(commands_router)
tg_dispatcher.include_router(conversation_router)
```

`commands_router` is included first so commands like `/start` are matched before the broader
conversation filters (which exclude `/`-prefixed text but the order still helps aiogram resolve
ambiguity).

## `commands_router` — `/start`, `/help`

```python
# kibernikto/telegram/handlers/commands.py
from aiogram import Router, types
from aiogram.filters import CommandStart, Command

commands_router = Router(name="commands_router")


@commands_router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "Hello! I am Kibernikto, your AI-powered assistant.\n"
        "Use /help to see available commands."
    )


@commands_router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Available commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message"
    )
```

This is the minimum useful help. To add a new admin command, decorate a function on
`commands_router` with `Command("<your_cmd>")` and decide whether you want it gated by
`TG_ADMIN_COMMANDS_ALLOWED` (the flag exists but is **not** currently enforced — the implementation
is reserved).

The `SubscriptionMiddleware.can_skip_subscription` static method does `text.startswith("/")`, so any
command automatically bypasses the subscription check.

## `conversation_router` — private, edited, group

The conversation router is intentionally thin: each handler applies a set of
aiogram filters, optionally gates on `should_react` (for groups), and then
delegates the full "Telegram message → agent → Telegram reply" loop to the
active `TelegramAgent` via
`kibernikto_telegram_agent.process_message(...)` and `.reply_to(...)`.

```python
# kibernikto/telegram/handlers/conversation.py
import logging
from aiogram import Router, F, enums
from aiogram.filters import or_f
from aiogram.types import Message

from kibernikto.telegram.agent import telegram_agent as _agent_module
from kibernikto.telegram.utils.permissions import should_react

logger = logging.getLogger(__name__)
conversation_router = Router(name="conversation_router")


async def _process_and_reply(message: Message) -> None:
    result = await _agent_module.kibernikto_telegram_agent.process_message(message)
    if result is None:
        return
    await _agent_module.kibernikto_telegram_agent.reply_to(message, result)


@conversation_router.message(
    F.chat.type == enums.ChatType.PRIVATE,
    ~F.text.startswith('/'),
    ~F.caption.startswith('/'),
)
async def handle_private_message(message: Message):
    user_id = message.from_user.id
    logger.info(f"Processing private message from user {user_id}")
    await _process_and_reply(message)


@conversation_router.edited_message(
    F.chat.type == enums.ChatType.PRIVATE,
    ~F.text.startswith('/'),
    ~F.caption.startswith('/'),
)
async def handle_edited_message(message: Message):
    user_id = message.from_user.id
    logger.info(f"Processing edited private message from user {user_id}: {message.md_text}")
    await _process_and_reply(message)


@conversation_router.message(
    or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP),
    ~F.text.startswith('/'),
    ~F.caption.startswith('/'),
)
async def handle_group_message(message: Message):
    user_id = message.from_user.id
    logger.info(f"Processing group message from user {user_id}: {message.text} in {message.chat.title}")

    if not should_react(message):
        logger.debug(f"skipping message from {user_id} in {message.chat.title}")
        return

    await _process_and_reply(message)
```

**Why the import is `telegram_agent as _agent_module`, not `kibernikto_telegram_agent`**: the
handler looks the agent up via the module at call time, so a
`set_telegram_agent(my_subclass)` call after import (but before the dispatcher
starts) is picked up automatically. Re-exporting the name would freeze the
binding at import time.

### Filters in plain English

| Handler | Chat types | Excludes | Reacts to |
|---|---|---|---|
| `handle_private_message` | `PRIVATE` | `/`-prefixed text and captions | every non-command message |
| `handle_edited_message` | `PRIVATE` | `/`-prefixed text | every edited message |
| `handle_group_message` | `GROUP` or `SUPERGROUP` | `/`-prefixed text | `should_react(message)` (name/keyword/reply) |

Stickers, service messages, new members, and other noise are blocked one layer up by the
`IGNORED_TYPES` set in `TelegramMessagePreprocessor` — the preprocessor returns `None` for those,
and the conversation handler short-circuits with `if result is None: return` so the model is never
called and no reply is sent.

### Preprocessor runs for all chat types

The previous version of this file flagged that the group and edited handlers
passed `message.text` directly while only the private handler called the
preprocessor. After the refactor, **all three handlers** go through
`kibernikto_telegram_agent.process_message(...)`, so photos, voice, replies
and forwards are preprocessed uniformly. The group handler still gates on
`should_react(...)` first, so multimodal only kicks in for messages the bot
is asked to react to.

### Adding a new conversation handler

1. Decorate with `conversation_router.message(...)` (or `.edited_message(...)`) and the relevant
   filters. Mirror the existing `~F.text.startswith('/'), ~F.caption.startswith('/')` exclusions.
2. Call `await _process_and_reply(message)` (the private helper in this module) — it handles
   pre-processing, running, error handling, and replying. Don't re-implement any of it.
3. If the new handler needs to gate on extra conditions (like the group handler gates on
   `should_react`), do that before the call. The shared helper takes care of the rest.

### Customising the agent

To plug in a subclass (e.g. one with extra tools or a different preprocessor),
build it from the same env-derived config and call `set_telegram_agent(...)`
**before** the dispatcher starts. The conversation handlers read the agent
via the module reference, so the swap is picked up automatically.

```python
from kibernikto.ai.agent import kibernikto_agent
from kibernikto.telegram.agent import TelegramAgent, set_telegram_agent


class MyAgent(TelegramAgent):
    pass


my_agent = MyAgent(
    model=kibernikto_agent.model,
    model_settings=kibernikto_agent.model_settings,
    system_prompt="You are Kibernikto's helpful cousin.",
)

set_telegram_agent(my_agent)
```

## Filters Reference

`aiogram` filter combos used here:

- `F.chat.type == enums.ChatType.PRIVATE` — match private chats only
- `or_f(F.chat.type == enums.ChatType.GROUP, F.chat.type == enums.ChatType.SUPERGROUP)` — match
  both group flavours
- `~F.text.startswith('/')` — exclude commands (aiogram supports `~` to invert a filter)
- `~F.caption.startswith('/')` — same, for media captions

## Logging Conventions

- `logger.info` for "received" lines (user id, chat title)
- `logger.debug` for skipped messages
- `logger.exception` (with `exc_info=True` by default) for caught errors
- `logger.warning` for permission denials (see [Middlewares](./TELEGRAM-MIDDLEWARES.md))

The `kibernikto` logger is set to `DEBUG` by `configure_logger()`, so info-level events are
captured by default in development.
