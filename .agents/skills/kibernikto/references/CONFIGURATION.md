# Configuration

Kibernikto uses [`pydantic_settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
throughout. There is **no** programmatic config — every setting reads from environment variables (or a
`.env` file passed via `--env_file_path`).

Five `*Settings` classes cover the framework. Each declares its own `env_prefix`:

| Prefix | Class | Location |
|---|---|---|
| `APP_` | `AppSettings` | `kibernikto/config.py` |
| `AGENT_KIBERNIKTO_` | `AgentKiberniktoSettings` | `kibernikto/ai/agent/core/config.py` |
| `TG_` | `TelegramSettings` | `kibernikto/telegram/config.py` |
| `SUBSCRIPTION_` | `SubscriptionSettings` | `kibernikto/telegram/middleware/middleware_subscription.py` |
| `TRANSCRIBE_*` (no prefix) | `PreprocessorSettings` | `kibernikto/telegram/pre_processors/_default.py` |

A reference `kibernikto.env` lives at `env_examples/kibernikto.env`. The CLI is:

```bash
kibernikto --env_file_path=/path/to/kibernikto.env
```

`main.py` calls `start(outer_env=True)`, which means **the host app** is responsible for loading the
`.env` (the CLI command itself uses `python-dotenv` internally).

## `APP_*` — Application Identity

| Variable | Default | Description |
|---|---|---|
| `APP_INSTANCE_NAME` | `"kibernikto-app"` | Logfire `service_name`, logger name, dispatcher name |
| `APP_URL` | `"https://none.com"` | Forwarded to `OpenRouterProvider(app_url=...)` for OpenRouter rankings |
| `APP_TAG_NAME` | `"kibernikto"` | Tag — currently informational |

## `AGENT_KIBERNIKTO_*` — Core Agent

| Variable | Default | Description |
|---|---|---|
| `AGENT_KIBERNIKTO_NAME` | `"kibernikto"` | Passed to `Agent(name=...)` |
| `AGENT_KIBERNIKTO_PROVIDER_TYPE` | `"openrouter"` | One of `openai`, `gateway`, `openrouter`, `vsegpt`, `custom_openai`. **Informational today** — the prefix in `AGENT_KIBERNIKTO_MODEL_NAME` is what actually routes in `infer_kibernikto_model`. |
| `AGENT_KIBERNIKTO_HISTORY_SIZE` | `6` | Window size for `MemoryHistoryStorage` |
| `AGENT_KIBERNIKTO_MODEL_NAME` | `"anthropic/claude-sonnet-4.6"` | See [Model providers](./CORE-AGENT.md#model-providers) |
| `AGENT_KIBERNIKTO_MODEL_MAX_TOKENS` | `760` | `ModelSettings.max_tokens` |
| `AGENT_KIBERNIKTO_MODEL_TEMPERATURE` | `0.7` | `ModelSettings.temperature` |
| `AGENT_KIBERNIKTO_MODEL_PARALLEL_TOOL_CALLS` | `True` | `ModelSettings.parallel_tool_calls` |
| `AGENT_KIBERNIKTO_MODEL_MODALITIES` | `['text']` | Subset of `'text'`, `'photo'`, `'audio'` |
| `AGENT_KIBERNIKTO_WHO_AM_I` | `DEFAULT_SYSTEM_PROMPT` | System prompt |

### Default system prompt

```text
Respond to all my questions as Kibernikto. Kibernikto is a gentle universe creator.
He isn't afraid to joke in a sinister manner. Kibernikto never tries to avoid a
specific answer including concrete names and events.
```

### Provider keys (read by `infer_kibernikto_model`)

These have no `AGENT_KIBERNIKTO_` prefix — they're the upstream provider keys:

| Variable | Used by |
|---|---|
| `VSEGPT_API_KEY` | `vsegpt:` prefix in `MODEL_NAME` |
| `ROUTER_AI_KEY` | `routerai:` prefix in `MODEL_NAME` |

OpenRouter needs no explicit key — it uses `OpenRouterProvider` which reads `OPENROUTER_API_KEY`
internally.

## `TG_*` — Telegram Bot

```python
# kibernikto/telegram/config.py
class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='TG_')
    BOT_KEY: str | None = None
    MASTER_ID: int = 199740245
    MASTER_IDS: List[int] = [199740245]
    PUBLIC: bool = True
    FRIEND_GROUP_IDS: List[int] | None = None
    PRIVILEGED_USERS: List[int] | None = None
    SERVICE_GROUP_ID: int | None = None
    CHUNK_SENTENCES: int = 1024
    REACTION_CALLS: List[str] = ['honda', 'киберникто']
    SAY_HI: bool = False
    STICKER_IDS: List[str] = ["CAACAgIAAxkBAAEQPFJpZpza5ISCVgABh0uT6CYX9HgwevYAAu5KAAK-HmBK9OlWUNgz8-w4BA"]
    STICKER_PROBABILITY: float = 0.13
    MAX_MESSAGE_LENGTH: int = 4096
    MAX_CAPTION_LENGTH: int = 1023
    ADMIN_COMMANDS_ALLOWED: bool = True
    FILES_LOCATION: str = "/tmp"
```

| Variable | Default | Description |
|---|---|---|
| `TG_BOT_KEY` | `None` | The bot token from `@BotFather`. **Required for the bot to start.** |
| `TG_MASTER_ID` | `199740245` | Main admin's numeric Telegram user ID |
| `TG_MASTER_IDS` | `[199740245]` | All admin user IDs (subset of MASTER_ID plus others) |
| `TG_PUBLIC` | `True` | When `True`, every private chat user can talk to the bot. When `False`, only admins can. |
| `TG_FRIEND_GROUP_IDS` | `None` | If set, the bot only responds in these group IDs. `None` = all groups. |
| `TG_PRIVILEGED_USERS` | `None` | Reserved for special-cased users (currently informational) |
| `TG_SERVICE_GROUP_ID` | `None` | If set, private messages are forwarded here (logging) and runtime errors are sent here. `None` disables both `ServiceMiddleware` and `ErrorsMiddleware`. |
| `TG_CHUNK_SENTENCES` | `1024` | Sentences per outgoing message chunk (re-exported as `MAX_MESSAGE_LENGTH` semantics, see notes below) |
| `TG_REACTION_CALLS` | `['honda', 'киберникто']` | In group chats, the bot reacts when any of these phrases appears or when its name/`@username` is mentioned or when someone replies to the bot |
| `TG_SAY_HI` | `False` | If `True`, send a random sticker to `TG_MASTER_ID` on bot startup |
| `TG_STICKER_IDS` | one example sticker ID | Sticker pool used by `send_random_sticker` |
| `TG_STICKER_PROBABILITY` | `0.13` | Reserved for the probability of sending a sticker with replies (currently not invoked in the default reply path) |
| `TG_MAX_MESSAGE_LENGTH` | `4096` | **Telegram hard cap** — don't change |
| `TG_MAX_CAPTION_LENGTH` | `1023` | **Telegram hard cap** — don't change |
| `TG_ADMIN_COMMANDS_ALLOWED` | `True` | Reserved flag for admin commands |
| `TG_FILES_LOCATION` | `"/tmp"` | Where to save downloaded voice / PDF files before processing |

### A few non-obvious things

- `TG_CHUNK_SENTENCES` is the historical name, but `conversation.py::reply` uses
  `MAX_MESSAGE_LENGTH = 4096` (the Telegram hard cap) as the chunk size. The variable is unused by
  the current reply path — `split_text_by_sentences` is called with `MAX_MESSAGE_LENGTH`, not
  `CHUNK_SENTENCES`.
- `TG_STICKER_PROBABILITY` is declared but **not read** by the default reply path. It's reserved for
  a future "send a sticker every N replies" feature.
- `MAX_MESSAGE_LENGTH` and `MAX_CAPTION_LENGTH` in `kibernikto/telegram/utils/conversation.py` are
  duplicates of the `TG_*` settings — they exist as module-level constants for quick access. Don't
  tune them; tune the env vars.

## `SUBSCRIPTION_*` — Telegram Stars

```python
# kibernikto/telegram/middleware/middleware_subscription.py
class SubscriptionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='SUBSCRIPTION_')
    ENABLED: bool = False
    PROMO_FREE_PROB: int = 45
    BASE_PRICE_STARS: int = 52
    ADDING_UP: int = 26
    POOR_CREDITS: int = 52
    TRIAL_CREDITS: int = 247
    RICH_CREDITS: int = 390
```

| Variable | Default | Description |
|---|---|---|
| `SUBSCRIPTION_ENABLED` | `False` | Master switch for the subscription middleware. When `False`, the middleware is not registered. |
| `SUBSCRIPTION_PROMO_FREE_PROB` | `45` | Percent probability of skipping the subscription check (free trial) |
| `SUBSCRIPTION_BASE_PRICE_STARS` | `52` | XTR price for the smallest tier |
| `SUBSCRIPTION_ADDING_UP` | `26` | Reserved increment (currently informational) |
| `SUBSCRIPTION_POOR_CREDITS` | `52` | Reserved tier name "poor" |
| `SUBSCRIPTION_TRIAL_CREDITS` | `247` | XTR price for the middle tier ("trial") |
| `SUBSCRIPTION_RICH_CREDITS` | `390` | XTR price for the top tier ("rich") |

The keyboard labels are `||`, `|||`, `|||||` — three columns, one row — and the actual prices are
read from the settings at request time.

## `TRANSCRIBE_*` — Whisper (no prefix!)

```python
# kibernikto/telegram/pre_processors/_default.py
class PreprocessorSettings(BaseSettings):
    TRANSCRIBE_PROCESSOR: Literal["openai", "elevenlabs", "auto"] | None = None
    TRANSCRIBE_OPENAI_API_KEY: str | None = None
    TRANSCRIBE_OPENAI_API_MODEL: str = "whisper-1"
    TRANSCRIBE_OPENAI_API_BASE_URL: str | None = None
    TRANSCRIBE_OPENAI_API_LANGUAGE: str | None = "ru"
    TRANSCRIBE_MIN_COMPLEX_SECONDS: int = 300
```

| Variable | Default | Description |
|---|---|---|
| `TRANSCRIBE_PROCESSOR` | `None` | Selector — currently the preprocessor always uses OpenAI. Other values are reserved. |
| `TRANSCRIBE_OPENAI_API_KEY` | `None` | OpenAI key for Whisper. **Required for voice/audio transcription** — without it, voice messages become a `Voice transcription error: no TRANSCRIBE_OPENAI_API_KEY configured` marker. |
| `TRANSCRIBE_OPENAI_API_MODEL` | `"whisper-1"` | Whisper model name |
| `TRANSCRIBE_OPENAI_API_BASE_URL` | `None` | Override the OpenAI base URL (useful with vsegpt) |
| `TRANSCRIBE_OPENAI_API_LANGUAGE` | `"ru"` | Language hint — pass `None` or remove the env var for auto-detect |
| `TRANSCRIBE_MIN_COMPLEX_SECONDS` | `300` | Reserved threshold — currently informational |

> ⚠️ The env example file (`env_examples/kibernikto.env`) also references `VOICE_*` keys. **Those are
> not read by the current code** — the framework reads `TRANSCRIBE_*` only. The `VOICE_*` names are
> a legacy alias that may still be present in user-deployed env files. Always set `TRANSCRIBE_*`
> when you change the preprocessor.

## `env_examples/kibernikto.env`

A reference file with safe placeholders. **Do not commit a real `.env`**: `.gitignore` already
excludes `.env` at the repo root, but a `kibernikto.env` accidentally committed is enough to leak the
bot key.

## Startup Banner

Each `*Settings` module exports a `print_banner()` that logs the resolved config (redacting
`TG_BOT_KEY` via `exclude={'BOT_KEY'}`). The full banner order on `kibernikto` startup is:

1. `kibernikto.config.print_banner()` → `APP_*`
2. `kibernikto.ai.agent.core.config.print_banner()` → `AGENT_KIBERNIKTO_*`
3. `kibernikto.telegram.config.print_banner()` → `TG_*` (bot key hidden)
4. `runner.init()` middleware activation log lines (`firewall middleware: ✅`, `logging middleware: 💤`, …)
