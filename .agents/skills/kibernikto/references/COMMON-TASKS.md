# Task Reference Map

Quick "I want to do X → read Y" index. Follow the links to the relevant reference file.

## Core Agent

| Task | Reference |
|---|---|
| Call `kibernikto_agent.run` from custom code | [Core Agent](./CORE-AGENT.md) |
| Add a tool to the existing singleton | [Core Agent → Adding Tools](./CORE-AGENT.md#adding-tools) |
| Subclass `KiberniktoAgent` for a separate agent | [Core Agent → Adding Tools](./CORE-AGENT.md#adding-tools) |
| Switch model providers (openrouter / vsegpt / routerai / openai) | [Core Agent → Model Routing](./CORE-AGENT.md#model-routing-infer_kibernikto_model) |
| Add a new provider | [Core Agent → Model Routing](./CORE-AGENT.md#model-routing-infer_kibernikto_model) |
| Replace `MemoryHistoryStorage` with a persistent backend | [Core Agent → History Storage](./CORE-AGENT.md#history-storage-memoryhistorystorage) |
| Use `TestModel` / `FunctionModel` in tests | [Core Agent → Testing](./CORE-AGENT.md#testing) |
| Understand binary attachments from tools | [Core Agent → Binary Attachments](./CORE-AGENT.md#binary-attachments-kiberniktodeps) |

## Configuration

| Task | Reference |
|---|---|
| All env vars at a glance | [Configuration](./CONFIGURATION.md) |
| Change system prompt / history size / modalities | [Configuration → AGENT_KIBERNIKTO_*](./CONFIGURATION.md#agentnikertosettings-agent_kibernikto_--kiberniktoaiagentcoreconfig) |
| Make the bot private or public | [Configuration → TG_PUBLIC](./CONFIGURATION.md#telegramsettings-tg_--kiberniktotelgramconfigpy) |
| Forward messages to a log group | [Configuration → TG_SERVICE_GROUP_ID](./CONFIGURATION.md#telegramsettings-tg_--kiberniktotelgramconfigpy) |
| Enable Telegram Stars paywall | [Configuration → SUBSCRIPTION_ENABLED](./CONFIGURATION.md#subscriptionsettings-subscription_) |
| Configure voice transcription | [Configuration → TRANSCRIBE_*](./CONFIGURATION.md#preprocessorsettings-transcribe_) |

## Telegram Handlers

| Task | Reference |
|---|---|
| Add `/mycommand` | [Telegram Handlers](./TELEGRAM-HANDLERS.md) |
| Add a new message type handler | [Telegram Handlers → Conversation Router](./TELEGRAM-HANDLERS.md#conversation-router) |
| Swap the agent without touching handlers | [Telegram Handlers → Swapping the Agent](./TELEGRAM-HANDLERS.md#swapping-the-agent) |
| Fix `result.output` vs `result.data` inconsistency | [Telegram Handlers → Known Quirks](./TELEGRAM-HANDLERS.md#known-quirks) |

## Preprocessing

| Task | Reference |
|---|---|
| Add a new content type (stickers, video notes) | [Telegram Preprocessing → Custom Preprocessor](./TELEGRAM-PREPROCESSING.md#custom-preprocessor) |
| Enable image understanding | [Telegram Preprocessing → Image Upload](./TELEGRAM-PREPROCESSING.md#image-upload) |
| Enable voice transcription | [Telegram Preprocessing](./TELEGRAM-PREPROCESSING.md) |
| Wire PDF parsing (currently stub) | [Telegram Preprocessing → Dispatch table](./TELEGRAM-PREPROCESSING.md#process_tg_message-dispatch) |

## Middlewares

| Task | Reference |
|---|---|
| Add a new middleware (rate limit, DB logger, etc.) | [Telegram Middlewares → Registration Order](./TELEGRAM-MIDDLEWARES.md#registration-order) |
| Fix the `or 1==1` forwarding bug | [Telegram Middlewares → ServiceMiddleware](./TELEGRAM-MIDDLEWARES.md#servicemiddleware-middleware_servicepy) |
| Implement the `PROMO_FREE_PROB` free trial | [Telegram Middlewares → SubscriptionMiddleware](./TELEGRAM-MIDDLEWARES.md#subscriptionmiddleware-middleware_subscriptionpy) |

## Payments

| Task | Reference |
|---|---|
| Change subscription period / price | [Payments](./PAYMENTS.md) |
| Understand the Stars payment flow | [Payments → Flow](./PAYMENTS.md#flow) |
| Add a thank-you message on payment | [Payments → Key Functions](./PAYMENTS.md#key-functions) |

## Utils / Runner / Logging

| Task | Reference |
|---|---|
| Run the bot from PyPI / from repo | [Utils, Runner & Logging](./UTILS-AND-RUNNER.md) |
| Reply with chunked long text | [Utils, Runner & Logging → Reply Helper](./UTILS-AND-RUNNER.md#reply-helper-kiberniktotelgramutilesconversationpy) |
| Upload image from a tool | [Utils, Runner & Logging → Image Utils](./UTILS-AND-RUNNER.md#image-utils-kiberniktoutils) |
| Send traces to Logfire | [Utils, Runner & Logging → Logging](./UTILS-AND-RUNNER.md#logging) |

## Architecture

| Task | Reference |
|---|---|
| Understand the three layers and request lifecycle | [Architecture](./ARCHITECTURE.md) |
| Trace a Telegram message end-to-end | [Architecture → Request Lifecycle](./ARCHITECTURE.md#request-lifecycle) |
| Find which settings class to add a field to | [Architecture → Settings Surface](./ARCHITECTURE.md#settings-surface) |
| Compare `KiberniktoAgent` vs `TelegramAgent` | [Architecture → Class Hierarchy](./ARCHITECTURE.md#class-hierarchy) |
