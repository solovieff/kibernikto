# Kibernikto Project Rules

## Project Context
Kibernikto is a multi-agent AI framework with Telegram bot integration, built on pydantic-ai + aiogram v3.
- Package: `kibernikto` (PyPI, v2.0.1)
- Core: `KiberniktoAgent` — a `pydantic_ai.Agent` subclass with injectable per-chat history; file-backed by default, PostgreSQL/SQLite via `APP_STORAGE_DATA_BACKEND`
- Telegram: aiogram dispatcher with conversation handlers, middlewares, multimodal preprocessor
- Dependencies: `pydantic-ai`, `aiogram`, `logfire`, `pydantic-ai-harness`
- Config: global settings via `pydantic_settings.BaseSettings` (env vars: `APP_*`, `APP_STORAGE_*`, `AGENT_KIBERNIKTO_*`, `TG_*`, `TRANSCRIBE_*`); agent constructors retain dependency-injection arguments

## Coding Conventions

### Imports
- In __init__ files maximum same packes relative imports. No __all__ etc.
- `chat_id` enables per-chat history for async `run` when `history_storage` is not `None`; omit it and automatic history is skipped

### Model Providers
- `openrouter:foo/bar` and `vsegpt:foo` — routed by `infer_kibernikto_model`
- Everything else falls through to `pydantic_ai.infer_model`

### Configuration
- Most global settings are env-only — don't pass as constructor args

### Architecture Layers
```
CLI (kibernikto command / main.py)
  ├── kibernikto.telegram (aiogram dispatcher)
  │     ├── handlers/  conversation handlers (private, group, edited)
  │     ├── middleware/ (message: Peer → optional Service → Firewall → optional Subscription)
  │     │               (edited: Peer context → Firewall; error: optional Errors)
  │     ├── pre_processors/ (text, photo, voice, audio; PDF parsing is a stub)
  │     ├── payment/ (Telegram Stars)
  │     └── agent/telegram_app.py (TelegramApp: Bot + Dispatcher + polling)
  ├── kibernikto.ai.agent
  │     ├── core/kibernikto_agent.py (KiberniktoAgent)
  │     ├── telegram/telegram_agent.py (TelegramAgent: process_message + reply_to)
  │     └── utils.py (infer_kibernikto_model)
  └── kibernikto.storage
        ├── base.py (HistoryStorage contract; opt-in MemoryHistoryStorage)
        ├── factory.py + singletons.py (backend selection + lazy defaults)
        └── file/ + sql/ + s3/ (history/chat data: file or SQL; media: file or S3)
```

### Agent Patterns
- Subclass `KiberniktoAgent` to add tools, change system prompt, swap model
- Subclass `TelegramAgent` in `kibernikto/ai/agent/telegram/telegram_agent.py` + call that module's `set_telegram_agent(...)` before the dispatcher starts; `agent.to_telegram()` builds the app but does not register the agent
- `agent.run` returns `AgentRunResult` — use `result.output` for text or structured output, not `result.data`

### Logging
- All logging through Logfire (`logfire.instrument_pydantic_ai()`)
- Prefer pydantic_ai patterns for new model calls (auto-traced)

## Known Gotchas

- **Preprocessing**: `TelegramAgent` accepts a `pre_processor=` instance; its settings are module-level state, so don't mutate runtime settings
- **History window alignment**: `get_conversation` walks back from last N messages to find a `request` — it's intentional, don't "fix" it
- **Subscription period**: hard-coded 30 days in `payment_utils.py` (`DEFAULT_SUBSCRIPTION_PERIOD = 2592000`)
- **ServiceMiddleware debug policy**: the historical `or 1 == 1` forwarding shortcut was deliberate, not an invitation to harden it. Current source skips admin messages and no longer contains that expression; do not change or reintroduce forwarding behavior merely to reconcile old documentation.

## Skills Available
- `.agents/skills/kibernikto/SKILL.md` — full framework reference, architecture, task routing table
- `.agents/skills/pydantic-ai-harness/SKILL.md` — CodeMode sandboxing
- `.agents/skills/building-pydantic-ai-agents/SKILL.md` — building pydantic-ai agents

## Python Style
Write code as an expert top level senior mega cto developer. Cold and effective pro. One line good comments!

Python Development (3.14+)

Core Philosophy

Stdlib and Mature Libraries First

Always prefer Python stdlib solutions
External deps only when stdlib insufficient
Prefer dataclasses over attrs, pathlib over os.path
Type Hints Everywhere (No Any)

Python 3.14 has lazy annotations by default
Use Protocol for structural typing (duck typing)
Avoid Any—use concrete types or generics
NEVER use typing.Optional. Use Type | None instead (e.g., str | None).
Protocol Over ABC

Protocol for implicit interface satisfaction
ABC only when runtime isinstance() needed
Protocols are more flexible and Pythonic
Flat Control Flow

Guard clauses with early returns
Pattern matching to flatten conditionals
Maximum 2 levels of nesting
Explicit Error Handling

Custom exception hierarchy for domain errors
Raise early, handle at boundaries
except ValueError | TypeError: (no parens)

## Build & Run
- Don't install packages yourself — ask first
- Read `pyproject.toml` for Python requirements, dependencies and the `kibernikto` entry point; use the existing virtual environment. No IDE configuration is required.
- From the repository root, check docs offline with `.venv/bin/python -B .agents/skills/kibernikto/scripts/check_docs.py`; add `--tests` to run unittest discovery in its isolated, network-blocked environment.
- Standard test command: `.venv/bin/python -B -m unittest discover -s tests -t .` in an already isolated test environment; prefer the helper above when live credentials or storage may be inherited.
- Authorized live run: `.venv/bin/python main.py` with configuration prepared before agent imports. Do not start polling without authorization or a second poller for an active bot token. See `.agents/skills/kibernikto/references/UTILS-AND-RUNNER.md` for startup details.
- On Windows, use the existing virtual environment's `Scripts/python.exe` instead of `.venv/bin/python`.