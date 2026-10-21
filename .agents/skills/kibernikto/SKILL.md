---
name: kibernikto
description: Use when developing Kibernikto agents or Telegram bots.
license: MIT
compatibility: Linux, macOS or Windows; use the existing repo environment, see pyproject.toml.
metadata:
  version: "4.0.0"
  author: Kibernikto Team, Hermes Agent
  tags: python agents telegram pydantic-ai
  related-skills: building-pydantic-ai-agents pydantic-ai-harness
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
| Telegram agent + active bridge | `kibernikto/ai/agent/telegram/telegram_agent.py`, `kibernikto/telegram/bridge.py` |
| Multi-agent orchestrator (parent wiring) | `kibernikto/ai/agent/telegram/multi_agent.py` |
| Harness capabilities (transport-free, keyed on `RunContext.conversation_id`): `CreditTier`, `chat_memory`, delegation roster, web layout, experts | `kibernikto/ai/agent/harness/` |
| Bot, Dispatcher, middleware order, lifecycle | `kibernikto/telegram/agent/telegram_app.py` |
| Handlers / middlewares / preprocessing | `kibernikto/telegram/handlers/`, `kibernikto/telegram/middleware/`, `kibernikto/telegram/pre_processors/` |
| Telegram peers (bot-to-bot subagents) | `kibernikto/ai/agent/telegram/peer_agent.py`, `kibernikto/telegram/peer_hub.py` |
| Stars subscription | `kibernikto/telegram/payment/payment_utils.py` |
| Storage contracts and backends | `kibernikto/storage/base.py`, `kibernikto/storage/factory.py` |
| Public image URLs (imgbb / S3) | `kibernikto/utils/image_hosting.py` |
| Logging, banner | `kibernikto/config.py` |
| Settings | grep `env_prefix` — one `BaseSettings` per module |
| Server deploy (podman + systemd, one folder per bot) | `deploy/README.md`, `deploy/scripts/_common.sh` |

Request path: `TelegramApp` → middlewares → handler → active `TelegramBridge.process_message`
→ `Agent.run` (`ConversationHistory` loads, steers, saves) → `reply_to`.

## Contracts and traps

**Configuration**
- Settings are module-level and resolve **at import**. Set env before importing; never mutate
  settings or swap storage singletons in a live process. The CLI loads dotenv before imports.
- Some fields are declared but unused. Grep for the consumer before relying on one.

**Agents**
- `TelegramApp.from_bridge(bridge)` registers the bridge; handlers resolve it per update via `get_telegram_bridge()`.
- Use `result.output` (text or structured), never `result.data`.
- Per-conversation history and mid-run steering exist in the overridden async `run` with `conversation_id=` and non-None
  `history_storage`. Concurrent `run(..., conversation_id=X)` calls while a run for `X` is active enqueue the new prompt
  into the live run (`priority='asap'`) and return `None`. An explicit `message_history` (even `[]`) skips loading; saving still happens.
- History window alignment walks back to a request and may return more than `HISTORY_SIZE`.
  Intentional — don't "fix" it.
- Importing core, harness or Telegram agent modules does not construct provider models or default agent
  instances. Report (needs `VSEGPT_API_KEY`) and scheduler (no execution daemon) stay opt-in and out of
  `harness/__init__.py` and default wiring.
- Agent `.reaction` emoji: `telegram/agent_reaction.py` `AgentReaction` sets it on `deps.message`.
  Delegates react at run start; the root (first starter, `deps.extra["reaction_root"]`) only on its own tool
  calls except `skip_tools` (`delegate_task`) — plain chatter gets none. Delegates react only via
  `SubAgents(shared_capabilities=[AgentReaction()])` (wired in `multi_agent.py`). Last emoji stays; peer
  envelopes and Telegram errors never react/fail.
- Bot menu = `handlers/commands.py` `COMMANDS`, published on startup by `set_bot_commands`; `/help` renders
  the same tuple. New command → add it there.
- Experts are plain `pydantic_ai.Agent`s delegated via the real `SubAgents(agents=[SubAgent(a)])`;
  only a parent with the `CreditTier` capability (`harness/credit_tier.py`, wired in
  `multi_agent.py`) selects tier models and spends credits. Peer envelopes set
  `KiberniktoDeps.billable=False`; explicit `run(model=...)`/`override(model=...)` beat the tier.
- `chat_data` (`ConversationInfo`) stores credits only; legacy JSON keys are ignored on load.
  `build_deps` loads it once into `KiberniktoDeps.chat_info` (read-only; tier selection reuses it) and
  writes nothing; `CreditTier.after_run` re-reads before charging so a mid-run top-up survives.
  Credits are kept out of the prompt. Timezone is `utils.time_utils.DEFAULT_TIMEZONE` (Moscow).
- Instructions per run, in order: persona (`{FILESTORE}/{NAME}-instructions.txt` **replaces** `WHO_AM_I`;
  read once at agent construction → restart to apply; unknown `{{field}}` fails at startup, escape as `\{{`
  or disable with `AGENT_KIBERNIKTO_PERSONA_TEMPLATE=false`), capability guidance (memory, roster), `Current date: …`
  (day granularity, cache-friendly), then Telegram bot identity and chat context. pydantic_ai sorts static text
  before callables, so a templated persona would sink: the persona is the named part `agent:persona` and
  `PersonaFirst` (`core/persona.py`) moves it back to the top. Experts pass `persona=False`: no `WHO_AM_I`, date kept.
- Persona text is a Handlebars template (`core/persona.py`, stock `TemplateStr`, needs `pydantic-ai-slim[spec]`)
  rendered against `Persona(name, traits)` — never against deps (aiogram `Message` inside). No `{{` → plain static
  string. Compiled at construction: an unknown field (`{{nmae}}`) raises then; no HTML escaping. Values come from
  `persona_source=` (a `PersonaSource` Protocol, per run); default `StaticPersona` = `PERSONA_NAME` or "Kibernikto",
  traits from `AGENT_KIBERNIKTO_PERSONA_TRAITS` JSON. `build_telegram_agent` defaults to `TelegramPersona`:
  `PERSONA_NAME` → bot `full_name` from getMe → "Kibernikto".
- Bot identity (`telegram/identity.py`): `fetch_bot_identity` runs once in `_on_startup` (getMe + descriptions,
  descriptions best-effort) into a `BotIdentity`; the prompt line, `{{name}}` and `should_react` all read it from
  memory. BotFather edits apply after restart. `display_name` is the Telegram name, not `AGENT_KIBERNIKTO_NAME`.
- Chat facts (`chat_context.get_chat_context`): getChat cached in process memory per (bot, chat),
  600 s TTL, never persisted; includes `pinned:` text. Pin/title/photo service messages hit
  `handle_chat_changed` → `forget_chat_context`. Failed getChat falls back to the update's `Chat`.
- Web: `ExaSearch` when `EXA_API_KEY` is set, else `Researcher(subagents=[])` spilling oversized
  tool output under `{FILESTORE}/tool-output` (1-day TTL), on the parent (tier model). Setting
  `AGENT_KIBERNIKTO_WEB_MODEL_NAME` drops those tools: web becomes a tool-less `web_researcher` delegate on a
  search-native model (e.g. `routerai:perplexity/sonar-reasoning-pro`). The roster text is ours
  (`harness/delegation.py`: `KiberniktoSubAgents` + `DELEGATION_GUIDE`; web wiring in `harness/web.py`), not the harness default.
- Memory is stock harness, on the parent: `chat_memory(name)` = `Memory` (namespace = `ctx.conversation_id`,
  store from `get_memory_store()`: file → `{FILESTORE}/memory`, sqlite → `*.memory.db`, pg →
  `PostgresMemoryStore`) + `ConversationSearch` over our own `HistoryStorage`, bound per run to
  the caller's conversation. No `StepPersistence`; `ConversationInfo` holds no facts about people.
  Live pg check (opt-in): `KIBERNIKTO_TEST_PG_DSN=postgresql+asyncpg://... python -m unittest tests.test_chat_memory`.

**Telegram**
- Module-level routers attach to one Dispatcher per process; tests patch `include_router`.
- Middleware is per observer (message, edited, error), not one chain. See `TelegramApp.from_bridge`.
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
- Every successful Stars payment (`/pay` top-up or subscription) adds 1 credit per Star to
  `chat_data`; no charge-id dedup by decision (a crash-redelivered update may credit twice). Top-ups work with `SUBSCRIPTION_ENABLED=false`.
  Admins (`TG_MASTER_ID(S)`, `TG_ADMIN_COMMANDS_ALLOWED`) adjust balances directly: `/pay ±N tg_id`, `/balance tg_id`.
- `/reset` (private: the user; groups: admins only, needs `TG_ADMIN_COMMANDS_ALLOWED`) asks for inline
  confirmation, then erases that chat's history and notebook (`storage/chat_wipe.py`). Credits and media stay.
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
from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent
from kibernikto.storage.base import MemoryHistoryStorage

async def smoke():
    history = MemoryHistoryStorage(history_size=6)
    agent = build_kibernikto_agent(model=TestModel(custom_output_text="ok"), name="smoke",
                                   history_storage=history)
    result = await agent.run("Hello", conversation_id="42")
    assert result.output == "ok" and await history.get_conversation("42")

asyncio.run(smoke())
```

## Verification

`.venv/bin/python -B .agents/skills/kibernikto/scripts/check_docs.py --tests` runs in an
isolated, network-blocked child with fake keys and temp storage. It checks this file's paths,
links and imports, runs the snippet above and the peer builder, then runs the unittest suite.
Report offline checks separately from live verification.
