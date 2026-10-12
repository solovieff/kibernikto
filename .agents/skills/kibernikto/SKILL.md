---
name: kibernikto
description: Use when developing Kibernikto agents or Telegram bots.
version: 4.0.0
author: Kibernikto Team, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
compatibility: Use the existing repo environment; see pyproject.toml.
metadata:
  hermes:
    tags: [python, agents, telegram, pydantic-ai]
    related_skills: [building-pydantic-ai-agents, pydantic-ai-harness]
---

# Kibernikto

pydantic-ai agents + harness delegation + pluggable storage + aiogram Telegram app.
**The code is the reference.** This skill lists only what reading one file won't tell you:
where things live, cross-module contracts and traps. Agents, tools, prompts and settings
fields change often — read them in source, don't trust a remembered list.

## Map

| Concern | Start here |
|---|---|
| CLI, dotenv, startup | `kibernikto/cmd/__start.py`, `main.py` |
| Base agent, history, attachments | `kibernikto/ai/agent/core/kibernikto_agent.py` |
| Model string → model | `kibernikto/ai/agent/utils.py` (`infer_kibernikto_model`) |
| Telegram agent + active-agent setter | `kibernikto/ai/agent/telegram/telegram_agent.py` |
| Credit tiers, local experts orchestrator | `kibernikto/ai/agent/extended/` |
| Expert agents | `kibernikto/ai/agent/harness/` |
| Bot, Dispatcher, middleware order, lifecycle | `kibernikto/telegram/agent/telegram_app.py` |
| Handlers / middlewares / preprocessing | `kibernikto/telegram/handlers/`, `kibernikto/telegram/middleware/`, `kibernikto/telegram/pre_processors/` |
| Telegram peers (bot-to-bot subagents) | `kibernikto/ai/agent/telegram/peer_agent.py`, `kibernikto/telegram/peer_hub.py` |
| Stars subscription | `kibernikto/telegram/payment/payment_utils.py` |
| Storage contracts and backends | `kibernikto/storage/base.py`, `kibernikto/storage/factory.py` |
| Public image URLs (imgbb / S3) | `kibernikto/utils/image_hosting.py` |
| Logging, banner | `kibernikto/config.py` |
| Settings | grep `env_prefix` — one `BaseSettings` per module |
| Server deploy (podman + systemd, one folder per bot) | `deploy/README.md`, `deploy/scripts/_common.sh` |

Request path: `TelegramApp` → middlewares → handler → active `TelegramAgent.process_message`
→ `KiberniktoAgent.run` → storage → `reply_to`.

## Contracts and traps

**Configuration**
- Settings are module-level and resolve **at import**. Set env before importing; never mutate
  settings or swap storage singletons in a live process. The CLI loads dotenv before imports.
- Some fields are declared but unused. Grep for the consumer before relying on one.

**Agents**
- Register a custom agent with `set_telegram_agent(agent)` before polling. `to_telegram()` builds
  the app only; handlers resolve the active agent per update.
- Use `result.output` (text or structured), never `result.data`.
- Per-chat history exists only in the overridden async `run` with `chat_id=` and non-None
  `history_storage`. An explicit `message_history` (even `[]`) skips loading; saving still happens.
- History window alignment walks back to a request and may return more than `HISTORY_SIZE`.
  Intentional — don't "fix" it.
- Importing an expert module builds its model. Report (needs `VSEGPT_API_KEY`) and scheduler
  (no execution daemon) are opt-in: keep them out of `harness/__init__.py` and default wiring.
- Experts are plain `KiberniktoAgent`s delegated via the real `SubAgents(agents=[SubAgent(a)])`;
  `KiberniktoExtended` is only for a credit-tiered parent. Agent credits are not Stars billing.

**Telegram**
- Module-level routers attach to one Dispatcher per process; tests patch `include_router`.
- Middleware is per observer (message, edited, error), not one chain. See `TelegramApp.from_agent`.
- Preprocessor settings are module-level shared state; treat as read-only.
- Voice is enabled by the presence of `TRANSCRIBE_OPENAI_API_KEY`. PDF extraction is a stub.
- Media store (private archive, `media/`) ≠ image hosting (public URLs for the model, `public/`).
  They share `APP_STORAGE_S3_*` credentials.

**Peers** (human docs: [docs/telegram-peers.md](../../../docs/telegram-peers.md))
- Waits are process-local futures, not durable jobs; SQL history doesn't change that.
- `TG_PEER_IDS` admits only *new* inbound requests from a bot; correlated answers need no entry.
  It never bypasses the firewall or subscription.
- If delivery silently fails between bots, check Telegram's **Restrict Bot Usage** on the
  receiving bot (it was the root cause on an old bot) before touching code.

**Payments / ops**
- The subscription period is fixed at 30 days (`DEFAULT_SUBSCRIPTION_PERIOD`) by design.
  The paywall has no admin exemption, and each checked message queries Telegram for transactions.
- ServiceMiddleware skips admins. Don't reintroduce the old `or 1 == 1` forwarding shortcut.
- Logging: `LogfireLoggingHandler` ignores formatters, so the console uses its own StreamHandler.
  Logfire's handler runs with `console_log=False` so each record prints once.

## Rules

- Use the existing venv. Don't install or sync, read live `.env` files, print secrets,
  or start polling/payments without explicit authorization. Never run a second poller per token.
- Offline tests use `TestModel`/`FunctionModel`, an injected `MemoryHistoryStorage`
  and fake Bot methods:

```python
import asyncio
from pydantic_ai.models.test import TestModel
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.storage.base import MemoryHistoryStorage

async def smoke():
    history = MemoryHistoryStorage(history_size=6)
    agent = KiberniktoAgent(model=TestModel(custom_output_text="ok"), name="smoke",
                            history_storage=history)
    result = await agent.run("Hello", chat_id=42)
    assert result.output == "ok" and await history.get_conversation(42)

asyncio.run(smoke())
```

## Verification

`.venv/bin/python -B .agents/skills/kibernikto/scripts/check_docs.py --tests` runs in an
isolated, network-blocked child with fake keys and temp storage. It checks this file's paths,
links and imports, runs the snippet above and the peer builder, then runs the unittest suite.
Report offline checks separately from live verification.
