# Configuration

Most settings are module-level `BaseSettings` instances, resolved from environment at
import time. Configure the process **before imports**; don't mutate global settings
in a live service. Agent constructors still accept `model=`, `history_storage=`,
`pre_processor=` and other documented injection points. Lists use JSON env values.
Defaults below are source defaults, not recommendations or verified provider availability.

## App

Source: `kibernikto/config.py`, prefix `APP_`.

| Field suffix | Default | Use |
|---|---|---|
| `INSTANCE_NAME` | `kibernikto-app` | logging service, Dispatcher name, OpenRouter title |
| `URL` | `https://none.com` | OpenRouter app URL |
| `TAG_NAME` | `kibernikto` | declared app metadata |

## Agent

Source: `kibernikto/ai/agent/core/config.py`, prefix `AGENT_KIBERNIKTO_`.

| Field suffix | Default | Use |
|---|---|---|
| `NAME` | `kibernikto` | configured agent name |
| `PROVIDER_TYPE` | `openrouter` | declared only; model prefix routes |
| `MODEL_NAME` | `openrouter:anthropic/claude-sonnet-5` | primary model |
| `IMAGE_MODEL_NAME` | `None` | optional image-generation model/tool |
| `MODEL_MAX_TOKENS` | `1300` | model settings |
| `MODEL_TEMPERATURE` | `0.3` | model settings |
| `MODEL_PARALLEL_TOOL_CALLS` | `true` | model settings |
| `HISTORY_SIZE` | `6` | window in model messages, request-aligned |
| `KEEP_THINKING_IN_HISTORY` | `false` | reasoning retention; see storage caveat |
| `MODEL_MODALITIES` | `["text"]` | declared list of text/photo/audio; not a preprocessor gate |
| `WHO_AM_I` | source persona | fallback instructions when named instruction file absent |
| `TRIAL_CREDITS` | `260` | new `ConversationInfo` balance |
| `POOR_CREDITS` | `30` | below this selects poor model |
| `RICH_CREDITS` | `500` | at/above this selects rich model |
| `POOR_MODEL` | `openrouter:google/gemini-2.5-flash` | low-credit model and image expert |
| `MEDIUM_MODEL` | `openrouter:anthropic/claude-sonnet-5` | medium-credit model |
| `RICH_MODEL` | `openrouter:anthropic/claude-sonnet-5` | high-credit model |

The conversation expert reads `AGENT_KIBERNIKTO_READ_MODEL` directly via `os.getenv`
(default `openrouter:google/gemini-3.5-flash-lite`); it is not a settings field.
Provider credentials: `OPENROUTER_API_KEY`, `VSEGPT_API_KEY`, `ROUTERAI_API_KEY`,
or provider-specific keys such as `OPENAI_API_KEY`. Never dump these values.

## Storage

Source: `kibernikto/storage/config.py`, prefix `APP_STORAGE_`.

| Field suffix | Default | Use |
|---|---|---|
| `FILESTORE_LOCATION` | `~/.kibernikto` | file root, instructions, temporary files |
| `DATA_BACKEND` | `file` | file/pg/sqlite |
| `MEDIA_BACKEND` | `file` | file/s3 |
| `PG_DSN` | `None` | required for pg |
| `SQLITE_PATH` | `:memory:` | persistent file must be explicitly configured |
| `HISTORY_WINDOW_SLACK` | `3` | SQL tail-fetch multiplier |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | `None` | all required for s3 |
| `S3_REGION` | `us-east-1` | region |
| `S3_ADDRESSING_STYLE` | `path` | path/virtual |
| `S3_CHECKSUM_CALCULATION` | `when_required` | when_required/when_supported |

See [Storage](STORAGE.md) for persistence and startup behavior. Media storage and
public image hosting are separate; choosing S3 does not replace image publishing.

## Telegram

Source: `kibernikto/telegram/config.py`, prefix `TG_`.

| Field suffix | Default | Use |
|---|---|---|
| `BOT_KEY` | `None` | required when constructing a live Bot, not when parsing settings |
| `MASTER_ID` | `199740245` | primary admin; configure your deployment explicitly |
| `MASTER_IDS` | `[]` | additional admin IDs |
| `PEER_IDS` | `[]` | opt-in for unsolicited new private bot requests, not correlated replies |
| `PUBLIC` | `true` | private access for non-admins |
| `FRIEND_GROUP_IDS` | `None` | None/empty permits groups; otherwise ID allowlist |
| `PRIVILEGED_USERS` | `None` | declared, not a firewall bypass |
| `SERVICE_GROUP_ID` | `None` | enables service forwarding and error-report observer |
| `REACTION_CALLS` | `["honda", "киберникто"]` | group substring triggers plus runtime bot identity |
| `SAY_HI` | `false` | send configured sticker to master at startup |
| `STICKER_IDS` | source list | stickers available to greeting helper |
| `STICKER_PROBABILITY` | `0.13` | declared; not used by the current reply path |
| `CHUNK_SENTENCES` | `1024` | declared; current reply splitter doesn't consume it |
| `MAX_MESSAGE_LENGTH` | `4096` | declared; reply module also has its own constant |
| `MAX_CAPTION_LENGTH` | `1023` | declared; reply module also has its own constant |
| `ADMIN_COMMANDS_ALLOWED` | `true` | declared; commands router does not consult it |
| `BOT_MESSAGE_DELAY` | `0.0` | positive value enables randomized group-bot delay up to 13s |
| `MARKDOWN_TO_HTML` | `true` | HTML conversion; false uses legacy Markdown |
| `FILES_LOCATION` | `/tmp` | legacy declaration; media temp paths come from storage |

`TG_PEER_IDS` does not bypass private firewall or subscriptions. Registration/calling
already admits the correlated answer; do not duplicate outbound subagents there.
See [Peers](TELEGRAM-PEERS.md) and [Middlewares](TELEGRAM-MIDDLEWARES.md).

## Subscription

Source: `kibernikto/telegram/middleware/middleware_subscription.py`, prefix `SUBSCRIPTION_`.

| Field suffix | Default | Use |
|---|---|---|
| `ENABLED` | `false` | register message paywall |
| `PROMO_FREE_PROB` | `45` | declared, unused; no implemented random free pass |
| `BASE_PRICE_STARS` | `52` | first invoice amount |
| `ADDING_UP` | `26` | declared, unused |
| `POOR_CREDITS` | `52` | declared, unused |
| `TRIAL_CREDITS` | `247` | middle invoice amount, not agent initial balance |
| `RICH_CREDITS` | `390` | largest invoice amount, not agent rich threshold |

The fixed 30-day period is code, not a `SUBSCRIPTION_PERIOD` field. Payment and agent
credit settings are distinct; no automatic credit top-up is wired. See [Payments](PAYMENTS.md).

## Transcription and image hosting

Source: `kibernikto/telegram/pre_processors/_default.py`, prefix `TRANSCRIBE_`.

| Field suffix | Default | Use |
|---|---|---|
| `PROCESSOR` | `None` | declared openai/elevenlabs/auto; not consulted by voice handler |
| `OPENAI_API_KEY` | `None` | actual gate for OpenAI transcription |
| `OPENAI_API_MODEL` | `whisper-1` | transcription model |
| `OPENAI_API_BASE_URL` | `None` | optional compatible endpoint |
| `OPENAI_API_LANGUAGE` | `ru` | language hint |
| `MIN_COMPLEX_SECONDS` | `300` | declared, unused |

`kibernikto/utils/image_hosting.py` reads `IMAGE_HOSTING_PROVIDER` (default `imgbb`,
only registered provider), `IMAGE_STORAGE_API_KEY` and `IMAGE_STORAGE_EXPIRATION`
(default `0`, no expiration). Not `IMGBB_API_KEY`.
`JINA_AI_API_KEY` configures the web/report integrations; see [Experts](AGENTS-AND-HARNESS.md).

## Superseded configuration notes

`TG_ALLOW_GROUPS`, `TG_BOT_MENTIONS`, `SUBSCRIPTION_PRICE`, `SUBSCRIPTION_PERIOD`,
`ROUTER_AI_KEY`, `IMGBB_API_KEY` and legacy `VOICE_*` names are not current settings.
The old exact pydantic-ai 1.106.0 pin is removed. CLI dotenv timing is described in
[Runtime](UTILS-AND-RUNNER.md); specifying a file after settings imports does not rebuild them.
