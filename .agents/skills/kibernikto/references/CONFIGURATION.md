# Configuration

All settings are `pydantic_settings.BaseSettings` — env vars only, no constructor args.

## AppSettings (`APP_*`) — `kibernikto/config.py`

| Env var | Default | Notes |
|---|---|---|
| `APP_INSTANCE_NAME` | `"kibernikto"` | Used in OpenRouter `app_title` header |
| `APP_URL` | `"https://kibernikto.ru"` | Used in OpenRouter `app_url` header |

## AgentKiberniktoSettings (`AGENT_KIBERNIKTO_*`) — `kibernikto/ai/agent/core/config.py`

| Env var | Default | Notes |
|---|---|---|
| `AGENT_KIBERNIKTO_NAME` | `"kibernikto"` | Agent `name=` in pydantic-ai |
| `AGENT_KIBERNIKTO_PROVIDER_TYPE` | `"openrouter"` | Declared but **not** used for routing — prefix in `MODEL_NAME` routes |
| `AGENT_KIBERNIKTO_MODEL_NAME` | `"anthropic/claude-sonnet-4.6"` | Prefix before `:` selects provider |
| `AGENT_KIBERNIKTO_MODEL_MAX_TOKENS` | `760` | `ModelSettings.max_tokens` |
| `AGENT_KIBERNIKTO_MODEL_TEMPERATURE` | `0.7` | `ModelSettings.temperature` |
| `AGENT_KIBERNIKTO_MODEL_PARALLEL_TOOL_CALLS` | `true` | `ModelSettings.parallel_tool_calls` |
| `AGENT_KIBERNIKTO_HISTORY_SIZE` | `6` | `MemoryHistoryStorage` window |
| `AGENT_KIBERNIKTO_MODEL_MODALITIES` | `["text"]` | Add `"photo"` / `"audio"` for multimodal |
| `AGENT_KIBERNIKTO_WHO_AM_I` | *(Kibernikto persona prompt)* | System prompt |

Provider API keys read directly from env (no prefix):

| Env var | Used by |
|---|---|
| `OPENAI_API_KEY` | pydantic-ai default OpenAI provider |
| `OPENROUTER_API_KEY` | OpenRouter provider |
| `VSEGPT_API_KEY` | `vsegpt:` prefix routing |
| `ROUTER_AI_KEY` | `routerai:` prefix routing |

## TelegramSettings (`TG_*`) — `kibernikto/telegram/config.py`

| Env var | Default | Notes |
|---|---|---|
| `TG_BOT_KEY` | *(required)* | Telegram bot token |
| `TG_MASTER_ID` | `None` | Admin user ID — bypasses firewall/subscription |
| `TG_PUBLIC` | `false` | If `false`, only `TG_MASTER_ID` can use the bot |
| `TG_REACTION_CALLS` | `[]` | Bot reacts in groups when message contains these strings |
| `TG_SERVICE_GROUP_ID` | `None` | Chat ID to forward all incoming messages to |
| `TG_ALLOW_GROUPS` | `false` | Enable group chat handling |
| `TG_BOT_MENTIONS` | `[]` | Bot username mentions that trigger group response |

## SubscriptionSettings (`SUBSCRIPTION_*`) — `kibernikto/telegram/middleware/middleware_subscription.py`

| Env var | Default | Notes |
|---|---|---|
| `SUBSCRIPTION_ENABLED` | `false` | Enable Telegram Stars paywall |
| `SUBSCRIPTION_PRICE` | `10` | Stars per period |
| `SUBSCRIPTION_PERIOD` | `2592000` | Seconds (30 days) — hard-coded in `payment_utils.py` |
| `SUBSCRIPTION_PROMO_FREE_PROB` | `0.0` | Probability of free access (unimplemented in current code) |

## PreprocessorSettings (`TRANSCRIBE_*`) — `kibernikto/telegram/pre_processors/_default.py`

> ⚠️ Note: prefix is `TRANSCRIBE_`, **not** `TG_` or `VOICE_`.

| Env var | Default | Notes |
|---|---|---|
| `TRANSCRIBE_PROCESSOR` | `None` | `"openai"` / `"elevenlabs"` / `"auto"` — enables voice transcription |
| `TRANSCRIBE_OPENAI_API_KEY` | `None` | Key for Whisper transcription |
| `TRANSCRIBE_OPENAI_API_MODEL` | `"whisper-1"` | Model used for transcription |
| `TRANSCRIBE_OPENAI_API_BASE_URL` | `None` | Custom base URL for transcription endpoint |
| `TRANSCRIBE_OPENAI_API_LANGUAGE` | `"ru"` | Language hint |
| `TRANSCRIBE_MIN_COMPLEX_SECONDS` | `300` | Voice files longer than this get extra processing |

## Startup Banner Order

On bot start, `print_banner()` logs JSON dumps of settings in this order:
1. `AppSettings`
2. `AgentKiberniktoSettings`
3. `TelegramSettings`
