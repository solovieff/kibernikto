# Utils, Runner & Logging

## Runner (`kibernikto/telegram/runner.py`)

Two public functions:

| Function | Purpose |
|---|---|
| `init(bot)` | Builds `Dispatcher`, includes routers, registers middlewares, wires payment handlers |
| `run_sync()` | Creates `Bot`, calls `init()`, starts `dp.run_polling(bot)` |

`run_sync()` is the entry point called by `kibernikto.cmd.__start:start()` and by `main.py`.

Middleware registration order in `init()`:
```
ServiceMiddleware.apply_if_needed(dp)
ErrorsMiddleware.apply_if_needed(dp)
FirewallMiddleware.apply_if_needed(dp)
SubscriptionMiddleware.apply_if_needed(dp)
```

## Text Utils (`kibernikto/utils/text.py`)

| Function | Purpose |
|---|---|
| `split_text(text, max_len)` | Splits long text into chunks ≤ `max_len` chars, respecting word boundaries |
| `escape_markdown(text)` | Escapes MarkdownV2 special chars for `parse_mode="MarkdownV2"` |

Used by `reply()` in `telegram/utils/conversation.py`.

## Image Utils (`kibernikto/utils/image.py`)

| Function | Purpose |
|---|---|
| `publish_image_file(bot, file_id)` | Download from Telegram → upload to imgbb → return public URL |

Requires `IMGBB_API_KEY` env var. Called by the preprocessor for photo messages.
`generate_image(prompt)` in `kibernikto/ai/agent/core/image.py` calls the model image generation API.

## Reply Helper (`kibernikto/telegram/utils/conversation.py`)

`reply(message, text, parse_mode="MarkdownV2")`:
- Splits text by `split_text` if too long for a single Telegram message (4096 char limit)
- Sends each chunk with `message.answer(...)`
- Falls back to plain text if Markdown parse fails

Used by `TelegramAgent.reply_to()`.

## Logging

`configure_logger()` in `kibernikto.cmd.__start`:
- Calls `logfire.configure()`
- Calls `logfire.instrument_pydantic_ai()` — auto-traces all pydantic-ai LLM calls
- Standard Python `logging` routes through Logfire

No custom log format needed — Logfire handles structured output. Add new model calls via
pydantic-ai patterns to get them traced automatically.

## Entry Points

| Entry | Code |
|---|---|
| `kibernikto` CLI | `kibernikto.cmd.__start:start` (via `pyproject.toml` scripts) |
| `main.py` | `from kibernikto.cmd import start; start(outer_env=True)` |

`outer_env=True` skips loading a `.env` file inside `__start.py` — caller is responsible for
env setup (e.g. `python-dotenv` or shell export).
`outer_env=False` (default when using the CLI) loads `--env_file_path` argument.
