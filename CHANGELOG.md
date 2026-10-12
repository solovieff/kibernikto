# Changelog

## 2.0.0b1 — first 2.x beta

Complete rewrite on [pydantic-ai](https://ai.pydantic.dev) + aiogram 3. Not API-compatible with 1.x:
the old executors, `kibernikto.bots`, `kibernikto.interactors` and plugins are gone. The Telegram
bot entry point (`kibernikto --env_file_path=...`) is unchanged.

### Highlights

- `KiberniktoAgent` (a `pydantic_ai.Agent`) with per-chat history; `--multi-agent` adds web,
  image and conversation experts via pydantic-ai-harness `SubAgents`.
- Telegram peer sub-agents: other Telegram bots as delegated experts, text or multimodal.
- Storage: history/chat data in files, SQLite or PostgreSQL; media in files or S3.
- Public image hosting: `imgbb` (default) or **`s3`** with a public base URL.
- Telegram Stars subscription checks with pre-checkout/successful-payment handlers.
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
- Stars billing has no durable entitlement ledger; credits are not topped up by payments.
- One poller per bot token; no built-in health endpoint.
