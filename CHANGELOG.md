# Changelog

## Unreleased

### Breaking
- `KiberniktoAgent` is gone: `build_kibernikto_agent()` returns a plain `pydantic_ai.Agent`
  with `ConversationHistory` (history + mid-run steering) and `PersonaCapability`.
  A steered run returns an empty result; check it with `is_steered(result)`.
- `TelegramAgent` is gone: `build_telegram_agent()` returns a plain `Agent[TelegramDeps]` with
  `TelegramCapability`; Telegram I/O lives in `TelegramBridge(agent)`; run with
  `TelegramApp.from_bridge(bridge)`. `get/set_telegram_agent` → `get/set_telegram_bridge`.
- Agent reaction emoji is `Agent(metadata={"reaction": "👀"})`, not an attribute.

## 2.0.0b1 — first 2.x beta

Complete rewrite on [pydantic-ai](https://ai.pydantic.dev) + aiogram 3. Not API-compatible with 1.x:
the old executors, `kibernikto.bots`, `kibernikto.interactors` and plugins are gone. The Telegram
bot entry point (`kibernikto --env_file_path=...`) is unchanged.

### Highlights

- `KiberniktoAgent` (a `pydantic_ai.Agent`) with per-chat history; `--multi-agent` builds a
  credit-tiered parent (`CreditTier` capability) with per-chat memory (harness `Memory` +
  `ConversationSearch`), web research (Exa when `EXA_API_KEY` is set, else the harness
  `Researcher`; or a tool-less delegate on a search-native model via `AGENT_KIBERNIKTO_WEB_MODEL_NAME`)
  and an image expert. Experts run without the persona.
- Harness capabilities are transport-free: `kibernikto.ai.agent.harness` (`CreditTier`, `chat_memory`,
  delegation, web) keys on `KiberniktoDeps.chat_id` / `billable` / `chat_info` / `timezone`, so they work
  on a plain `KiberniktoAgent`. The Telegram multi-agent assembly is `kibernikto.ai.agent.telegram.multi_agent`
  (`build_multi_agent`, `build_multi_agent_with_tg_peers`).
- Persona: `WHO_AM_I` / `{NAME}-instructions.txt` may be a Handlebars template
  (`{{name}}`, `{{traits.x}}`; `AGENT_KIBERNIKTO_PERSONA_NAME`, `AGENT_KIBERNIKTO_PERSONA_TRAITS`).
  An unknown `{{field}}` fails at startup: escape literal braces as `\{{`, or set
  `AGENT_KIBERNIKTO_PERSONA_TEMPLATE=false` to treat the persona as plain text.
- `/reset`: erases a chat's history and the bot's notes after confirmation (credits stay);
  in groups only admins can do it.
- Agent reactions: `KiberniktoAgent(reaction=emoji)` + `AgentReaction` mark the user's message —
  delegates on start (`image-agent` ✍, `web-agent` 👨‍💻, peers 🤝), the parent (`AGENT_KIBERNIKTO_REACTION`,
  default 👀) only on its own tool calls. Plain chatter gets none.
- Bot menu: commands are published via `set_my_commands` on startup; `/help` renders the same list.
- Telegram peer sub-agents: other Telegram bots as delegated experts, text or multimodal.
- Storage: history/chat data/memory in files, SQLite or PostgreSQL; media in files or S3.
- Public image hosting: `imgbb` (default) or **`s3`** with a public base URL.
- Telegram Stars: subscription checks plus `/pay [stars]` top-ups (1 ⭐ = 1 credit) and
  `/balance`; admins adjust balances with `/pay ±N tg_id`, `/balance tg_id`.
- Model HTTP errors become user-facing messages; reports go to the service group.
- Logging: one formatted console line per record, everything (including third-party
  warnings) exported to Logfire when `LOGFIRE_TOKEN` is set; agent spans in the console.
- Docker image (`python:3.14-slim`, non-root, state in `/data`) and a deployment runbook.

### Migrating from 1.10.x

Start from [`deploy/tg_bots/kibernikto/kibernikto.env`](deploy/tg_bots/kibernikto/kibernikto.env).

| 1.x | 2.0 |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | provider key for the model prefix, e.g. `OPENROUTER_API_KEY` |
| `OPENAI_API_MODEL` | `AGENT_KIBERNIKTO_MODEL_NAME=openrouter:vendor/model` |
| `OPENAI_MAX_TOKENS`, `OPENAI_TEMPERATURE` | `AGENT_KIBERNIKTO_MODEL_MAX_TOKENS`, `AGENT_KIBERNIKTO_MODEL_TEMPERATURE` |
| `OPENAI_MAX_MESSAGES` | `AGENT_KIBERNIKTO_HISTORY_SIZE` (model messages) |
| `OPENAI_WHO_AM_I` | `AGENT_KIBERNIKTO_WHO_AM_I` or `{FILESTORE}/{NAME}-instructions.txt` |
| `VOICE_OPENAI_API_KEY`, `VOICE_OPENAI_API_MODEL`, `VOICE_OPENAI_API_BASE_URL` | `TRANSCRIBE_OPENAI_API_KEY`, `TRANSCRIBE_OPENAI_API_MODEL`, `TRANSCRIBE_OPENAI_API_BASE_URL` |
| `TG_STICKER_LIST` | `TG_STICKER_IDS` |
| `TG_FILES_LOCATION`, `VOICE_FILE_LOCATION` | `APP_STORAGE_FILESTORE_LOCATION` |
| `IMGBB_API_KEY` | `IMAGE_STORAGE_API_KEY` |

1.x chat history is not migrated; conversations start fresh.

### Known limitations

- PDF/document parsing is a stub; documents produce an explanatory marker.
- Peer sub-agent waits are in-memory; restarts drop in-flight remote calls.
- Stars billing has no durable ledger or charge-id dedup; a redelivered payment update may credit twice.
- Requires Python 3.14+.
- One poller per bot token; no built-in health endpoint.
