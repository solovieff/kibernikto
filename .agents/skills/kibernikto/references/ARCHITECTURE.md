# Architecture

Kibernikto is a small, opinionated framework built on two upstream libraries: **`pydantic-ai`** for the
agent runtime and **`aiogram`** v3 for the Telegram bot. Everything in `kibernikto/` is glue plus a few
framework-specific conveniences.

## Package Layout

```
kibernikto/
├── __init__.py                # empty — the package is a namespace
├── config.py                  # AppSettings (APP_*), configure_logger(), print_banner()
│
├── ai/agent/                  # Pydantic-AI core (no Telegram dependency)
│   ├── __init__.py            # re-exports: from .core import agent as kibernikto_agent
│   ├── utils.py               # infer_kibernikto_model + provider constructors
│   └── core/
│       ├── __init__.py        # re-exports: from .kibernikto_agent import agent
│       ├── config.py          # AgentKiberniktoSettings (AGENT_KIBERNIKTO_*)
│       ├── history.py         # MemoryHistoryStorage, history_storage singleton
│       └── kibernikto_agent.py# KiberniktoAgent subclass + module-level `agent` singleton
│
├── telegram/                  # aiogram v3 dispatcher
│   ├── __init__.py
│   ├── config.py              # TelegramSettings (TG_*)
│   ├── runner.py              # init(), run_sync(), run_async(), on_startup()
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── commands.py        # /start, /help
│   │   └── conversation.py    # private / group / edited_message
│   ├── pre_processors/
│   │   ├── __init__.py        # re-exports: from ._default import TelegramMessagePreprocessor
│   │   └── _default.py        # multimodal Message → list[UserContent]
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── utils.py           # get_event_message(event) → Message | None
│   │   ├── middleware_firewall.py
│   │   ├── middleware_service.py    # ServiceMiddleware + ErrorsMiddleware
│   │   └── middleware_subscription.py
│   ├── payment/
│   │   ├── __init__.py
│   │   └── payment_utils.py   # create_payment_link, check_sub (Telegram Stars XTR)
│   ├── agent/
│   │   ├── __init__.py            # re-exports: TelegramAgent, kibernikto_telegram_agent, set_telegram_agent
│   │   └── telegram_agent.py  # TelegramAgent (extends KiberniktoAgent) + kibernikto_telegram_agent singleton
│   └── utils/
│       ├── __init__.py
│       ├── conversation.py    # reply, _text_reply, is_reply, get_message_text, send_random_sticker
│       └── permissions.py     # is_from_admin, admin_or_public, is_public, group_allowed, should_react
│
├── cmd/
│   ├── __init__.py
│   └── __start.py             # argparse + load_dotenv + configure_logger + runner.run_sync()
│
└── utils/                     # framework-agnostic helpers
    ├── __init__.py
    ├── image.py               # publish_image_file() → imgbb URL
    ├── text.py                # split_text, clear_text_format, prepare_for_MARKDOWN
    └── timer.py
```

## Three Layers

| Layer | Module | Dependency | Purpose |
|---|---|---|---|
| **Entry point** | `kibernikto.cmd.__start`, `main.py` | stdlib + `dotenv` | Parse `--env_file_path`, configure logging, hand off to runner |
| **Telegram** | `kibernikto.telegram.*` | `aiogram` v3 | Receive updates, run middlewares, preprocess, hand off to core |
| **Core agent** | `kibernikto.ai.agent.*` | `pydantic-ai` 1.106 | Run the LLM with per-chat history, return `AgentRunResult` |

The Telegram layer is **fully optional** — `kibernikto.ai.agent` is a self-contained pydantic-ai agent
that can be embedded in any async Python app.

## Request Lifecycle (Telegram → Core)

```
Telegram Update
    │
    ▼
aiogram Dispatcher
    │
    ▼ outer_middleware (registered in this order)
┌────────────────────────────────────────────────────────────────┐
│  1. ServiceMiddleware       forwards private msgs to service   │
│  2. ErrorsMiddleware        catches handler exceptions        │
│  3. FirewallMiddleware      admin/public/group access check   │
│  4. SubscriptionMiddleware  Star subscription check           │
└────────────────────────────────────────────────────────────────┘
    │
    ▼ aiogram router
┌────────────────────────────────────────────────────────────────┐
│  commands_router       /start, /help                          │
│  conversation_router   private messages + edited + group      │
└────────────────────────────────────────────────────────────────┘
    │
    ▼ handler (always delegates to kibernikto_telegram_agent)
kibernikto_telegram_agent.process_message(message)
    │
    ├─ 1. pre_processor.process_tg_message(message) → list[UserContent] | None
    │        (text, ImageUrl, voice transcript, reply/forward markers, …)
    │        None ⇒ handler short-circuits, no model call, no reply.
    │
    ├─ 2. background "typing…" chat action (every 4s) started
    │
    ├─ 3. self.run(user_message, chat_id=message.chat.id)
    │         (KiberniktoAgent.run override — loads/saves per-chat history)
    │
    ├─ 4. ModelHTTPError / Exception caught → return str with the error text
    │
    └─ 5. typing task cancelled and awaited
    │
    ▼
AgentRunResult | str | None
    │
    ▼ handler
kibernikto_telegram_agent.reply_to(message, result)
    │
    ├─ result is None ⇒ no-op
    └─ result is str / AgentRunResult ⇒ reply() helper
            (Markdown formatting, long-message chunking, image/audio/video/PDF
             attachments from ModelResponse)
```

## Re-export Chain

Worth memorising because debuggers and stack traces show the **original** import path:

| Public import | Re-exported from | Original location |
|---|---|---|
| `from kibernikto.ai.agent import kibernikto_agent` | `kibernikto/ai/agent/__init__.py` | `kibernikto/ai/agent/core/kibernikto_agent.py` (module-level `agent`) |
| `from kibernikto.telegram.agent import TelegramAgent, kibernikto_telegram_agent, set_telegram_agent` | `kibernikto/telegram/agent/__init__.py` | `kibernikto/telegram/agent/telegram_agent.py` |
| `from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor` | `kibernikto/telegram/pre_processors/__init__.py` | `kibernikto/telegram/pre_processors/_default.py` |
| `from kibernikto.telegram.handlers import conversation_router, commands_router` | `kibernikto/telegram/handlers/__init__.py` | per-file modules |
| `from kibernikto.ai.agent.core import agent` | `kibernikto/ai/agent/core/__init__.py` | same `agent` singleton |

## Settings Surface

All settings use `pydantic_settings.BaseSettings` with `env_prefix`:

| Prefix | Class | Used for |
|---|---|---|
| `APP_` | `AppSettings` (`kibernikto/config.py`) | Instance name, URL, Logfire service name |
| `AGENT_KIBERNIKTO_` | `AgentKiberniktoSettings` (`kibernikto/ai/agent/core/config.py`) | Model, system prompt, history size, modalities |
| `TG_` | `TelegramSettings` (`kibernikto/telegram/config.py`) | Bot token, admin IDs, public mode, friend groups, stickers, reactions |
| `SUBSCRIPTION_` | `SubscriptionSettings` (`kibernikto/telegram/middleware/middleware_subscription.py`) | Star prices, free-trial probability |
| `TRANSCRIBE_*` (no prefix!) | `PreprocessorSettings` (`kibernikto/telegram/pre_processors/_default.py`) | Whisper key, language, model |

The `env_examples/kibernikto.env` file ships commented-out defaults for the supported variables.
Detailed reference: [Configuration](./CONFIGURATION.md).

## Two Agent Classes

Kibernikto ships two `pydantic_ai.Agent` subclasses that look similar but serve different roles:

### `KiberniktoAgent` — the canonical one

```python
# kibernikto/ai/agent/core/kibernikto_agent.py
class KiberniktoAgent(Agent):
    async def run(self, *args, chat_id: int | None = None, **kwargs) -> AgentRunResult:
        if chat_id is not None and 'message_history' not in kwargs:
            kwargs['message_history'] = history_storage.get_conversation(chat_id)

        run_result: AgentRunResult = await super().run(*args, **kwargs)

        if chat_id is not None:
            history_storage.add_messages(chat_id=chat_id, messages=run_result.new_messages())

        return run_result


agent = KiberniktoAgent(
    model=model,
    model_settings=model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    system_prompt=AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I,
)
```

**Behaviour**: if `chat_id` is given, pre-loads conversation history and writes new messages back. The
overridden `run` is the *only* Kibernikto-specific behaviour — everything else is plain pydantic-ai.

### `TelegramAgent` — the Telegram-specialised agent

```python
# kibernikto/telegram/agent/telegram_agent.py
class TelegramAgent(KiberniktoAgent):
    def __init__(self, *, pre_processor: TelegramMessagePreprocessor | None = None, **kwargs):
        super().__init__(**kwargs)
        self._pre_processor = pre_processor or TelegramMessagePreprocessor()

    @property
    def pre_processor(self) -> TelegramMessagePreprocessor: ...

    async def process_message(self, message: Message) -> AgentRunResult | str | None:
        # 1. pre_processor.process_tg_message(message) -> list[UserContent] | None
        # 2. background "typing…" chat action (every 4s)
        # 3. self.run(user_message, chat_id=message.chat.id)
        #    (the KiberniktoAgent.run override above)
        # 4. catch ModelHTTPError / Exception -> return str
        # 5. cancel typing task
        ...

    async def reply_to(self, message: Message, result: AgentRunResult | str | None) -> None:
        if result is None:
            return
        await reply(message, result)


kibernikto_telegram_agent: TelegramAgent = TelegramAgent(
    model=kibernikto_agent.model,
    model_settings=kibernikto_agent.model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    system_prompt=AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I,
)


def set_telegram_agent(agent: TelegramAgent) -> TelegramAgent:
    """Replace the active singleton. Returns the previous agent."""
    global kibernikto_telegram_agent
    previous = kibernikto_telegram_agent
    kibernikto_telegram_agent = agent
    return previous
```

**Behaviour**: `TelegramAgent` is a `KiberniktoAgent` subclass that knows how to deal with aiogram
`Message` objects. The two public methods own the Telegram-specific glue that used to live in the
conversation handlers:

* `process_message(message)` — preprocesses the message via the configurable
  `pre_processor` (default `TelegramMessagePreprocessor`), runs the inherited
  `KiberniktoAgent.run(...)` with per-chat history, keeps Telegram's
  "typing…" indicator alive, and converts `ModelHTTPError` / `Exception` to plain
  `str` return values. Returns `None` if there was nothing to process.
* `reply_to(message, result)` — delegates to the shared `reply()` helper, which
  handles Markdown formatting, long-message chunking, and any images / audio /
  video / PDFs the model attached to its `ModelResponse`.

**Wiring**: the default `conversation_router` reads the active agent from
`kibernikto_telegram_agent` at call time (via the `telegram_agent` module
reference, not the imported name), so calling `set_telegram_agent(my_subclass)`
before the dispatcher starts is enough to plug in a custom subclass.

## History Storage

`MemoryHistoryStorage` (`kibernikto/ai/agent/core/history.py`) is the only history backend shipped:

- In-memory, process-local `defaultdict[int, list[ModelMessage]]` keyed by `chat_id`.
- `HISTORY_SIZE` (default `6`) bounds the window. `get_conversation` returns the last `HISTORY_SIZE`
  messages, then walks **backwards** until a message with `kind == 'request'` is found (so a partial
  history always starts on a user turn).
- `add_messages(chat_id, messages)` appends. The agent's `run` override calls this with
  `result.new_messages()` after every successful run.
- **No persistence**: restart = empty history. The singleton `history_storage` lives in
  `kibernikto/ai/agent/core/history.py`.

## Logging

`kibernikto.config.configure_logger()`:

1. Configures Logfire with `service_name=APP_SETTINGS.INSTANCE_NAME` and
   `send_to_logfire='if-token-present'`.
2. Calls `logfire.instrument_pydantic_ai()` so every model request is traced.
3. Adds a `LogfireLoggingHandler` to the root logger with a level-based formatter.
4. Sets `kibernikto` logger to `DEBUG`, `aiogram` and `pydantic_ai` to `INFO`.

The `print_banner()` helpers (one per settings module) log the resolved configuration on startup
(redacting the bot key).
