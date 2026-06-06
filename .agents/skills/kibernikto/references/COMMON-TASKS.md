# Task Reference Map

A condensed index of "I want to do X" → "read reference Y" so you can find the right file in one
hop. For deeper context, follow the links.

## Core Agent (`kibernikto.ai.agent`)

| Task | Reference |
|---|---|
| Use `kibernikto_agent.run` from custom code | [Core Agent → KiberniktoAgent](./CORE-AGENT.md#kiberniktoagent) |
| Add a tool to the existing `kibernikto_agent` | [Core Agent → Adding Tools](./CORE-AGENT.md#adding-tools) |
| Subclass `KiberniktoAgent` for a second agent | [Core Agent → Adding Tools](./CORE-AGENT.md#adding-tools) |
| Switch model providers (openrouter / vsegpt / openai / anthropic) | [Core Agent → Model providers](./CORE-AGENT.md#model-providers) |
| Add a new provider | [Core Agent → Add a new provider](./CORE-AGENT.md#add-a-new-provider) |
| Replace `MemoryHistoryStorage` with a persistent backend | [Core Agent → Replace the storage](./CORE-AGENT.md#replace-the-storage) |
| Use `TestModel` / `FunctionModel` for unit tests | [Core Agent → Testing](./CORE-AGENT.md#testing) |

## Configuration / Settings

| Task | Reference |
|---|---|
| Read all env vars at a glance | [Configuration](./CONFIGURATION.md) |
| Customise the system prompt | [Configuration → AGENT_KIBERNIKTO_WHO_AM_I](./CONFIGURATION.md#agent_kibernikto_--core-agent) |
| Change the history window | [Configuration → HISTORY_SIZE](./CONFIGURATION.md#agent_kibernikto_--core-agent) |
| Enable image / audio modalities | [Configuration → MODEL_MODALITIES](./CONFIGURATION.md#agent_kibernikto_--core-agent) |
| Restrict the bot to a friend group | [Configuration → TG_FRIEND_GROUP_IDS](./CONFIGURATION.md#tg_--telegram-bot) |
| Make the bot private (admin-only) | [Configuration → TG_PUBLIC](./CONFIGURATION.md#tg_--telegram-bot) |
| Forward private messages to a log group | [Configuration → TG_SERVICE_GROUP_ID](./CONFIGURATION.md#tg_--telegram-bot) |
| Enable Telegram Stars paywall | [Configuration → SUBSCRIPTION_ENABLED](./CONFIGURATION.md#subscription_--telegram-stars) |
| Add a sticker on bot start | [Configuration → TG_SAY_HI](./CONFIGURATION.md#tg_--telegram-bot) |
| Read the resolved config on startup | [Configuration → Startup Banner](./CONFIGURATION.md#startup-banner) |

## Telegram Handlers

| Task | Reference |
|---|---|
| Add `/mycommand` | [Telegram Handlers → commands_router](./TELEGRAM-HANDLERS.md#commands_router--start-help) |
| Add a new chat-type handler (private / group / edited) | [Telegram Handlers → conversation_router](./TELEGRAM-HANDLERS.md#conversation_router--private-edited-group) |
| Make the edited / group handlers stop crashing on `result.data` | [Telegram Handlers → Known quirk](./TELEGRAM-HANDLERS.md#known-quirk-resultoutput-vs-resultdata) |
| Enable multimodal in groups (currently text-only) | [Telegram Handlers → Why the preprocessor runs only for private messages](./TELEGRAM-HANDLERS.md#why-the-preprocessor-runs-only-for-private-messages) |
| Catch model errors and surface them to the user | [Telegram Handlers → Adding a new conversation handler](./TELEGRAM-HANDLERS.md#adding-a-new-conversation-handler) |

## Preprocessing

| Task | Reference |
|---|---|
| Add a new content type (e.g. stickers, video notes) | [Telegram Preprocessing → Replacing the preprocessor](./TELEGRAM-PREPROCESSING.md#replacing-the-preprocessor) |
| Switch the image host from imgbb to S3 | [Telegram Preprocessing → Photo](./TELEGRAM-PREPROCESSING.md#photo) |
| Wire up PDF parsing (currently a stub) | [Telegram Preprocessing → Documents](./TELEGRAM-PREPROCESSING.md#documents-pdf-only-admin-only) |
| Use Whisper through vsegpt | [Telegram Preprocessing → Voice & audio](./TELEGRAM-PREPROCESSING.md#voice--audio) |
| Recurse into a reply chain | [Telegram Preprocessing → Reply context](./TELEGRAM-PREPROCESSING.md#reply-context) |
| Include forwarded content (currently only the marker) | [Telegram Preprocessing → Forwards](./TELEGRAM-PREPROCESSING.md#forwards) |

## Middlewares

| Task | Reference |
|---|---|
| Add a new middleware (rate limit, DB logger, etc.) | [Telegram Middlewares → Adding a New Middleware](./TELEGRAM-MIDDLEWARES.md#adding-a-new-middleware) |
| Choose who gets forwarded to the service group | [Telegram Middlewares → ServiceMiddleware](./TELEGRAM-MIDDLEWARES.md#servicemiddleware--forward-private-messages) |
| Customise the "Access is denied!" reply | [Telegram Middlewares → FirewallMiddleware](./TELEGRAM-MIDDLEWARES.md#firewallmiddleware--access-control) |
| Make the bot leave non-friend groups | [Telegram Middlewares → Customising access control](./TELEGRAM-MIDDLEWARES.md#customising-access-control) |
| Implement the `PROMO_FREE_PROB` free trial | [Telegram Middlewares → Skip rules](./TELEGRAM-MIDDLEWARES.md#skip-rules) |
| Add a privileged user (bypass firewall but not admin) | [Telegram Middlewares → Customising access control](./TELEGRAM-MIDDLEWARES.md#customising-access-control) |

## Payments

| Task | Reference |
|---|---|
| Change subscription period | [Payments → create_payment_link](./PAYMENTS.md#create_payment_link) |
| Relabel the three pricing buttons | [Payments → Subscription keyboard](./PAYMENTS.md#subscription-keyboard) |
| Tone down the "MORTAL DETECTED" copy | [Payments → Subscription keyboard](./PAYMENTS.md#subscription-keyboard) |
| Send a thank-you message on `successful_payment` | [Payments → End-to-end flow](./PAYMENTS.md#end-to-end-flow) |
| Test Stars locally | [Payments → Testing payments locally](./PAYMENTS.md#testing-payments-locally) |
| Mock `check_sub` in unit tests | [Payments → Testing payments locally](./PAYMENTS.md#testing-payments-locally) |

## Utils / Runner / Logging

| Task | Reference |
|---|---|
| Run the bot from PyPI install | [Utils, Runner & Logging → Entry Points](./UTILS-AND-RUNNER.md#entry-points) |
| Run the bot from this repo | [Utils, Runner & Logging → main.py](./UTILS-AND-RUNNER.md#entry-points) |
| Embed the bot in an existing asyncio app | [Utils, Runner & Logging → Programmatic](./UTILS-AND-RUNNER.md#entry-points) |
| Reply with a long text and have it chunked | [Utils, Runner & Logging → Telegram Utils](./UTILS-AND-RUNNER.md#telegram-utils) |
| Send a document / image attachment in a reply | [Utils, Runner & Logging → Telegram Utils](./UTILS-AND-RUNNER.md#telegram-utils) |
| Reset `tg_bot` / `tg_dispatcher` between tests | [Utils, Runner & Logging → init() is not idempotent across processes](./UTILS-AND-RUNNER.md#init-is-not-idempotent-across-processes) |
| Add a new CLI flag | [Utils, Runner & Logging → Adding a Custom CLI Flag](./UTILS-AND-RUNNER.md#adding-a-custom-cli-flag) |
| Send traces to Logfire | [Utils, Runner & Logging → Logging Setup](./UTILS-AND-RUNNER.md#logging-setup) |
| Use a module-level logger | [Utils, Runner & Logging → Customising the logger](./UTILS-AND-RUNNER.md#customising-the-logger) |
| Parse JSON out of noisy model output | [Utils, Runner & Logging → text.py](./UTILS-AND-RUNNER.md#framework-agnostic-utils) |

## Architecture / Big Picture

| Task | Reference |
|---|---|
| Understand the three layers | [Architecture → Three Layers](./ARCHITECTURE.md#three-layers) |
| Trace a Telegram message through the system | [Architecture → Request Lifecycle](./ARCHITECTURE.md#request-lifecycle-telegram--core) |
| Find where a public import is re-exported from | [Architecture → Re-export Chain](./ARCHITECTURE.md#re-export-chain) |
| Decide which `*Settings` class to add a field to | [Architecture → Settings Surface](./ARCHITECTURE.md#settings-surface) |
| Compare `KiberniktoAgent` vs `TelegramAgent` | [Architecture → Two Agent Classes](./ARCHITECTURE.md#two-agent-classes) |
| Replace history with Redis / Postgres | [Architecture → History Storage](./ARCHITECTURE.md#history-storage) |
| Tweak the logfire logging pipeline | [Architecture → Logging](./ARCHITECTURE.md#logging) |
