---
name: kibernikto
description: Work with the Kibernikto framework — a multi-agent AI system built on pydantic-ai with a ready-made Telegram bot integration. Use when the user mentions Kibernikto, the `kibernikto` Python package, KiberniktoAgent, Kibernikto Telegram bot, the `kibernikto` CLI command, or any of the framework's modules (aiogram dispatcher, voice transcription, Telegram Stars payments, imgbb image upload, group/subscription/firewall middlewares, `AGENT_KIBERNIKTO_*` / `TG_*` env vars). Also use when modifying files under `kibernikto/` or the `main.py` / `env_examples/kibernikto.env` entry points.
license: MIT
compatibility: Requires Python 3.11+ and pydantic-ai==1.106.0
metadata:
  version: "2.0.1"
  author: Kibernikto Team
---

# Kibernikto Framework

Kibernikto is a multi-agent AI framework with a ready-made Telegram bot connection. The package
ships:

- **Core** — a `KiberniktoAgent` subclass of `pydantic_ai.Agent` with built-in per-chat history
  management, multi-provider model inference (OpenAI, OpenRouter, vsegpt, routerai), and pydantic-settings
  based configuration.
- **Telegram** — an `aiogram` v3 dispatcher with conversation handlers, three middlewares (firewall,
  service, subscription), a multimodal message preprocessor (text, photo, voice, audio, PDF, replies,
  forwards), and Telegram Stars payment integration.

You can use the core agent without Telegram (it's a regular `pydantic_ai.Agent`) and wire it into your own
app, or run the full Telegram bot via the `kibernikto` CLI command.

## When to Use This Skill

Invoke this skill when:

- The user mentions **Kibernikto**, the `kibernikto` PyPI package, `KiberniktoAgent`, or the
  `kibernikto` CLI command
- Code imports from `kibernikto.*` (e.g. `kibernikto.ai.agent`, `kibernikto.telegram.*`)
- Editing files under `kibernikto/`, `main.py`, `env_examples/kibernikto.env`, or `scripts/`
- Touching `AGENT_KIBERNIKTO_*`, `TG_*`, `SUBSCRIPTION_*`, or `APP_*` environment variables
- Working on aiogram handlers, Telegram middlewares, voice transcription (Whisper), image upload to
  imgbb, or Telegram Stars (`XTR`) subscription flow
- The user asks to add a tool, swap a model provider, change the system prompt, customize the
  preprocessor, or extend access control

Do **not** use this skill for:

- Generic `pydantic_ai` questions unrelated to Kibernikto — use the `building-pydantic-ai-agents` skill
- `aiogram` questions unrelated to Kibernikto's dispatcher layout
- The `pydantic-ai-harness` / CodeMode sandboxing (use the `pydantic-ai-harness` skill)

## Mental Model

Kibernikto is organised in **three layers**:

```
┌──────────────────────────────────────────────────────────────────┐
│  CLI entry: kibernikto → kibernikto.cmd.__start:start            │
│  main.py  → start(outer_env=True)                                │
└──────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┴────────────────┐
                ▼                                ▼
   ┌────────────────────────┐       ┌────────────────────────────┐
   │ kibernikto.telegram    │       │  kibernikto.ai.agent       │
   │ (aiogram dispatcher)   │       │  (pydantic_ai.Agent)       │
   │                        │       │                            │
   │  runner.run_sync()     │       │  KiberniktoAgent.run(      │
   │  handlers/             │◀──────│     user_message,          │
   │  middleware/           │extends│     chat_id=chat_id)       │
   │  pre_processors/       │       │  )                         │
   │  payment/              │       │  ├─ history_storage        │
   │  agent/                │       │  ├─ infer_kibernikto_model │
   │    TelegramAgent       │       │  └─ AgentKiberniktoSettings│
   │      .process_message  │       │                            │
   │      .reply_to         │       │  kibernikto_agent (singleton)│
   │                        │       │                            │
   │  kibernikto_telegram_  │       │                            │
   │  agent (singleton)     │       │                            │
   │                        │       │                            │
   │  config: TG_*          │       │                            │
   └────────────────────────┘       └────────────────────────────┘
```

The default conversation handlers always call
`kibernikto_telegram_agent.process_message(message)` and, if the result is not `None`,
`kibernikto_telegram_agent.reply_to(message, result)`. Both methods live on the
`TelegramAgent` subclass; ``process_message`` internally invokes
``self.run(user_message, chat_id=chat_id)`` which is the ``KiberniktoAgent.run`` override that
loads/saves per-chat history.

The **Telegram layer** turns aiogram updates into a list of `UserContent` items and hands them to
**`kibernikto_telegram_agent.process_message(message)`** (which internally calls
`kibernikto_agent.run(..., chat_id=...)` and replies via
`kibernikto_telegram_agent.reply_to(message, result)`). The core agent loads per-chat history from
`MemoryHistoryStorage`, runs the LLM, and writes new messages back. The Telegram layer adds the
"typing…" indicator and delegates the response rendering (text chunking, Markdown, binary
attachments) to the shared `reply()` helper.

**Two agent shapes are present in the codebase.** Use them accordingly:

- `kibernikto_agent` (`kibernikto.ai.agent.core.kibernikto_agent.agent`) — the canonical configured
  `KiberniktoAgent` singleton built from `AGENT_KIBERNIKTO_SETTINGS`. Always imported as
  `from kibernikto.ai.agent import kibernikto_agent`. Use it directly when you embed the agent in a
  non-Telegram app.
- `TelegramAgent` (`kibernikto.telegram.agent.telegram_agent.TelegramAgent`) — a `KiberniktoAgent`
  subclass that encapsulates the full Telegram conversation lifecycle
  (`process_message` + `reply_to`). The default conversation handlers always delegate to the
  module-level `kibernikto_telegram_agent` singleton, which is built from the same env-derived
  config as `kibernikto_agent`. Subclass `TelegramAgent` to add tools, swap the preprocessor, or
  override the response strategy — then call `set_telegram_agent(my_agent)` before the dispatcher
  starts.

## Quick Start Patterns

### Run the Telegram bot

```bash
# from PyPI
pip install kibernikto
kibernikto --env_file_path=/path/to/kibernikto.env

# from this repo
python main.py
```

`main.py` is a one-liner: `from kibernikto.cmd import start; start(outer_env=True)`.
`outer_env=True` means the caller is responsible for loading env vars (so `python-dotenv` is skipped
inside `__start.py`).

### Use `KiberniktoAgent` directly (no Telegram)

```python
import asyncio
from kibernikto.ai.agent import kibernikto_agent


async def main():
    result = await kibernikto_agent.run(
        "Привет! Кто ты?",
        chat_id=12345,  # any stable int — drives the per-chat history bucket
    )
    print(result.output)


asyncio.run(main())
```

`chat_id` is the only Kibernikto-specific parameter. If omitted, the agent behaves like a plain
`pydantic_ai.Agent` and no history is persisted.

### Subclass `KiberniktoAgent` to add tools

```python
from pydantic_ai import RunContext
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent import kibernikto_agent  # base singleton


my_agent = KiberniktoAgent(
    model=kibernikto_agent.model,
    model_settings=kibernikto_agent.model_settings,
    system_prompt="You are a helpful Kibernikto cousin.",
)


@my_agent.tool
async def get_time(ctx: RunContext) -> str:
    """Return current server time."""
    from datetime import datetime
    return datetime.now().isoformat()
```

Both `my_agent` and `kibernikto_agent` share the module-level `history_storage` singleton — no extra
wiring needed.

### Subclass `TelegramAgent` to customise the bot

When you want to keep the default dispatcher but plug in your own agent
behaviour, subclass `TelegramAgent` and call `set_telegram_agent(...)` before
the dispatcher starts. The default conversation handlers will then dispatch
to your subclass via `process_message` / `reply_to`.

```python
from pydantic_ai import RunContext

from kibernikto.ai.agent import kibernikto_agent  # base singleton, for model + settings
from kibernikto.telegram.agent import TelegramAgent, set_telegram_agent


class MyAgent(TelegramAgent):
    pass


my_agent = MyAgent(
    model=kibernikto_agent.model,
    model_settings=kibernikto_agent.model_settings,
    system_prompt="You are Kibernikto's helpful cousin.",
)


@my_agent.tool
async def get_time(ctx: RunContext) -> str:
    """Return current server time."""
    from datetime import datetime
    return datetime.now().isoformat()


set_telegram_agent(my_agent)  # take effect before the dispatcher starts polling
```

Override any of these to customise behaviour:

* `pre_processor` (property / ctor kwarg) — replace the multimodal
  `Message → list[UserContent]` strategy.
* `process_message(message)` — change how the message is turned into agent
  input, e.g. add a system prefix, suppress the typing loop, or branch on
  chat type.
* `reply_to(message, result)` — change how the response is sent (custom
  chunking, additional buttons, etc.).

### Configure via env

All settings are `pydantic_settings.BaseSettings` instances — set env vars (or pass a `.env` file
via `--env_file_path`) to override defaults. See [Configuration](./references/CONFIGURATION.md).

```env
APP_INSTANCE_NAME=my-kibernikto
APP_URL=https://my.site
AGENT_KIBERNIKTO_PROVIDER_TYPE=openrouter
AGENT_KIBERNIKTO_MODEL_NAME=openrouter:anthropic/claude-sonnet-4-5
AGENT_KIBERNIKTO_MODEL_MAX_TOKENS=760
AGENT_KIBERNIKTO_MODEL_TEMPERATURE=0.7
AGENT_KIBERNIKTO_HISTORY_SIZE=6
AGENT_KIBERNIKTO_MODEL_MODALITIES=["text", "photo"]
AGENT_KIBERNIKTO_WHO_AM_I="Respond as Kibernikto — a gentle universe creator."

TG_BOT_KEY=...:...
TG_MASTER_ID=199740245
TG_PUBLIC=true
TG_REACTION_CALLS=["киберникто", "honda"]
```

## Task Routing Table

Load only the most relevant reference first. Read additional references only if the task spans
multiple areas.

| I want to... | Reference |
|---|---|
| Understand package layout, layers, request lifecycle | [Architecture](./references/ARCHITECTURE.md) |
| Use `KiberniktoAgent`, add tools, manage history, switch model providers | [Core Agent](./references/CORE-AGENT.md) |
| Set env vars, customise system prompt, modalities, history size, access lists | [Configuration](./references/CONFIGURATION.md) |
| Add/edit conversation handlers (private, group, edited) or commands | [Telegram Handlers](./references/TELEGRAM-HANDLERS.md) |
| Add/edit preprocessor logic (text, photo, voice, audio, PDF, reply, forward) | [Telegram Preprocessing](./references/TELEGRAM-PREPROCESSING.md) |
| Tune access control, service logging, errors, or Star subscriptions | [Telegram Middlewares](./references/TELEGRAM-MIDDLEWARES.md) |
| Add/adjust the Telegram Stars payment flow | [Payments](./references/PAYMENTS.md) |
| Tweak text splitting, image upload, or run the entry points | [Utils, Runner & Logging](./references/UTILS-AND-RUNNER.md) |
| Follow an older link into `COMMON-TASKS.md` | [Task Reference Map](./references/COMMON-TASKS.md) |

## Key Practices

- **Always import the singleton as `kibernikto_agent`**:
  `from kibernikto.ai.agent import kibernikto_agent`. Don't re-instantiate `Agent(...)` with the same
  model — `kibernikto_agent` is configured from `AGENT_KIBERNIKTO_SETTINGS` and is the object the
  Telegram handlers already call.
- **Use `chat_id` for history, not the full conversation object**. The core agent stores messages in
  a process-local `MemoryHistoryStorage` keyed by `chat_id`. There is no Redis/DB layer — history is
  lost on restart.
- **Set the right `PROVIDER_TYPE`/`MODEL_NAME` prefix**. `openrouter:foo/bar` and `vsegpt:foo` are
  routed by `infer_kibernikto_model`; anything else falls through to `pydantic_ai.infer_model`. See
  [Core Agent → Model providers](./references/CORE-AGENT.md#model-providers).
- **`pre_processor` returns `list[UserContent] | None`** — not a string. Text, photos (as `ImageUrl`),
  transcriptions, and reply/forward markers are mixed into a single list and passed to
  `kibernikto_agent.run` as a single argument. The core agent does not parse strings.
- **Middlewares are applied in order**: `ServiceMiddleware → ErrorsMiddleware → FirewallMiddleware →
  SubscriptionMiddleware`. Adding a new middleware means appending to the `middlewares` list in
  `kibernikto/telegram/runner.py::init()` and writing `apply_if_needed(dispatcher)` as a `@staticmethod`.
- **Configuration is env-only**. Don't pass settings as constructor args; let
  `pydantic_settings` resolve them. Env vars override the defaults declared in each `*Settings`
  class.
- **Logging goes through Logfire**. `configure_logger()` calls
  `logfire.instrument_pydantic_ai()`; if you add new model calls, prefer `pydantic_ai` patterns so
  they get traced automatically.

## Common Gotchas

- **`chat_id` is `int | None` in `KiberniktoAgent.run`**. If you forget to pass it, history is
  silently skipped — your agent will appear "amnesic" only between calls in the same process.
  Outside Telegram, pass any stable int to enable history.
- **`agent.run` returns `AgentRunResult`**, not a string. Use `result.output` for the model text or
  `result.data` if you configured `output_type=BaseModel`. The current Telegram handlers use
  `result.output` (private) **and** `result.data` (group / edited) inconsistently — see
  [Telegram Handlers](./references/TELEGRAM-HANDLERS.md#known-quirk-resultoutput-vs-resultdata).
- **`HistoryHistoryStorage.get_conversation` aligns to a `request` message** at the window start.
  The window is the last `AGENT_KIBERNIKTO_HISTORY_SIZE` messages, then walked back until a
  `kind == 'request'` is found. Sending a partial history is intentional — don't "fix" it to
  always start at index 0.
- **`should_react` import is broken** in
  `kibernikto/telegram/utils/permissions.py:should_react` — it imports
  `from telegram.utils.conversation import is_reply, get_message_text`, which is the wrong top-level
  package. It should be `from kibernikto.telegram.utils.conversation import ...`. The default bot
  config ships a different `REACTION_CALLS` (e.g. `honda`, `киберникто`) so this only blows up in
  groups with replies, not in plain keyword-triggered groups.
- **`ServiceMiddleware.forward_message_service_group` has `or 1 == 1`**, which forwards **every**
  private message including admin messages. The `# FIXME DEBUG` comment is real — tighten it to
  `or not is_from_admin(message)` if you want admin-only forwarding, or `and not is_from_admin(...)`
  for everyone-except-admin.
- **`TelegramMessagePreprocessor` is global state**. The handlers call
  `TelegramMessagePreprocessor()` fresh on every message, but `_default` keeps a module-level
  `SETTINGS` and `IGNORED_TYPES` constant — fine for reads, not safe for mutating them at runtime.
- **Telegram Stars subscription period is hard-coded** to 30 days
  (`DEFAULT_SUBSCRIPTION_PERIOD = 2592000` in `kibernikto/telegram/payment/payment_utils.py`).
  Change it together with the display copy in `SubscriptionMiddleware.get_payment_keyboard`.
- **`PreprocessorSettings` prefix is `TRANSCRIBE_`** (not `TG_` or `VOICE_`). All
  transcription-related env vars must be named `TRANSCRIBE_OPENAI_API_KEY`, `TRANSCRIBE_PROCESSOR`,
  etc. Double-check if your `.env` file uses any legacy `VOICE_*` names — they will be silently
  ignored.
- **`pydantic-ai==1.106.0` is pinned exactly** in `pyproject.toml`. Don't bump it without testing
  the `KiberniktoAgent.run` override — pydantic-ai's `AgentRunResult.new_messages()` signature has
  shifted across versions.
