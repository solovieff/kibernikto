# Kibernikto Project Rules

## Project Context
Kibernikto is a multi-agent AI framework with Telegram bot integration, built on pydantic-ai + aiogram v3.
- Package: `kibernikto` (PyPI, v2.0.1)
- Core: `KiberniktoAgent` — a `pydantic_ai.Agent` subclass with per-chat `MemoryHistoryStorage`
- Telegram: aiogram dispatcher with conversation handlers, middlewares, multimodal preprocessor
- Dependencies: `pydantic-ai`, `aiogram`, `logfire`, `pydantic-ai-harness`
- Config: env-only via `pydantic_settings.BaseSettings` (env vars: `AGENT_KIBERNIKTO_*`, `TG_*`, `TRANSCRIBE_*`)

## Coding Conventions

### Imports
- In __init__ files maximum same packes relative imports. No __all__ etc.
- `chat_id` enables per-chat history; omit it and history is silently skipped

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
  │     ├── middleware/ (Service → Errors → Firewall → Subscription)
  │     ├── pre_processors/ (multimodal: text, photo, voice, audio, PDF)
  │     ├── payment/ (Telegram Stars)
  │     └── agent/ (TelegramAgent: process_message + reply_to)
  └── kibernikto.ai.agent (KiberniktoAgent core)
        ├── history_storage (MemoryHistoryStorage, process-local)
        └── infer_kibernikto_model
```

### Agent Patterns
- Subclass `KiberniktoAgent` to add tools, change system prompt, swap model
- Subclass `TelegramAgent` + call `set_telegram_agent(...)` before dispatcher starts to customize the bot
- `agent.run` returns `AgentRunResult` — use `result.output` (text) or `result.data` (structured)

### Logging
- All logging through Logfire (`logfire.instrument_pydantic_ai()`)
- Prefer pydantic_ai patterns for new model calls (auto-traced)

## Known Gotchas

- **`TelegramMessagePreprocessor` is global state** — read-only access is fine, don't mutate runtime settings
- **History window alignment**: `get_conversation` walks back from last N messages to find a `request` — it's intentional, don't "fix" it
- **Subscription period**: hard-coded 30 days in `payment_utils.py` (`DEFAULT_SUBSCRIPTION_PERIOD = 2592000`)
- **ServiceMiddleware** has `or 1 == 1` — this forwards ALL private messages (including admin). Tighten if needed.

## Skills Available
- `.agents/skills/kibernikto/SKILL.md` — full framework reference, architecture, task routing table
- `.agents/skills/pydantic-ai-harness/SKILL.md` — CodeMode sandboxing
- `.agents/skills/building-pydantic-ai-agents/SKILL.md` — building pydantic-ai agents

## Python Style
Write code as an expert top level senior mega cto developer. Cold and effective pro. One line good comments!

## Build & Run
- Don't install packages yourself — ask first
- Check `.idea/runConfigurations/` before running tests or code