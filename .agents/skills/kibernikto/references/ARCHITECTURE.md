# Architecture

Paths below are repository-relative. Python modules, not historical diagrams, define the API.

## Source map

| Layer | Source | Responsibility |
|---|---|---|
| CLI | `kibernikto/cmd/__start.py`, `main.py` | dotenv, logging, validation, agent selection, polling |
| Core | `kibernikto/ai/agent/core/kibernikto_agent.py` | `KiberniktoAgent`, configured `agent`, async history and attachments |
| Model routing | `kibernikto/ai/agent/utils.py` | provider-prefixed model inference |
| Telegram agent | `kibernikto/ai/agent/telegram/telegram_agent.py` | dependencies, preprocessing, model invocation, reply |
| Context | `kibernikto/ai/agent/telegram/chat_context.py`, `kibernikto/ai/agent/telegram/identity.py` | chat facts, bot identity instructions |
| Extended agent | `kibernikto/ai/agent/extended/kibernikto_extended.py` | named history, credit-based model selection and charging |
| Orchestrator | `kibernikto/ai/agent/extended/orchestrators.py` | local experts and optional peer builder |
| Experts | `kibernikto/ai/agent/harness/` | conversation, image, web, report, scheduler |
| Telegram app | `kibernikto/telegram/agent/telegram_app.py` | Bot, Dispatcher, startup/shutdown, peer hub |
| Transport | `kibernikto/telegram/handlers/`, `kibernikto/telegram/pre_processors/`, `kibernikto/telegram/utils/` | update routing, content conversion, rendering |
| Access/payment | `kibernikto/telegram/middleware/`, `kibernikto/telegram/payment/` | observer middleware, Stars lookup |
| Peers | `kibernikto/ai/agent/telegram/peer_agent.py`, `kibernikto/telegram/peer_hub.py` | remote text model and process-local correlation |
| Storage | `kibernikto/storage/base.py`, `kibernikto/storage/factory.py`, `kibernikto/storage/singletons.py` | protocols, backend selection and lazy proxies |
| Backends | `kibernikto/storage/file/`, `kibernikto/storage/sql/`, `kibernikto/storage/s3/` | JSON/files, PostgreSQL/SQLite, S3 media |

## Request lifecycle

1. `TelegramApp.from_agent` creates a Bot (HTML default) and Dispatcher. It does **not**
   set the active agent; handlers resolve the module-level agent at invocation time.
2. Peer middleware first consumes a matched private reply. Otherwise it sets the app's
   hub in a context variable and continues into the appropriate observer's middleware.
3. Commands precede conversation routing. Conversation handlers emit one typing action,
   then call active `agent.process_message(message)` and `agent.reply_to(message, result)`.
4. `TelegramAgent` guards private bot traffic, preprocesses content, refreshes persisted
   chat facts and builds `TelegramDeps`; group input includes author/time annotations.
5. `KiberniktoAgent.run` optionally loads history, invokes pydantic-ai, materializes tool
   attachments, archives/publishes generated images, then appends sanitized history.
6. `reply` renders `result.output` plus media. Expected peer replies bypass this entire
   conversation path rather than being fed back as new user requests.

See [middleware observers](TELEGRAM-MIDDLEWARES.md), not a single linear
Service → Errors → Firewall diagram: errors use a separate observer.

## Agent hierarchy and state

`Agent` → `KiberniktoAgent` → `TelegramAgent` → `KiberniktoExtended`.
`TelegramPeerAgent` subclasses `KiberniktoAgent` with a Telegram-backed model, not
`TelegramAgent` or `KiberniktoExtended`.

`kibernikto.ai.agent` re-exports `kibernikto_agent`, `kibernikto_model`,
`TelegramAgent`, `TelegramDeps`, `kibernikto_telegram_agent`, `set_telegram_agent`
and `KiberniktoDeps`. These package imports eagerly construct configured agents;
"usable without polling" does not mean "no Telegram imports/settings".

Default core/Telegram agents share the lazy `default` history namespace. Extended
agents select their own name via the factory. Chat data is shared across agent names;
media namespaces distinguish generated (`default`) and Telegram-uploaded (`telegram`) files.
See [Storage](STORAGE.md).

## Superseded descriptions

There is no `kibernikto/telegram/runner.py` or `kibernikto/ai/agent/core/history.py`.
The old `kibernikto/telegram/agent/telegram_agent.py` location is removed; the
transport package holds `TelegramApp`. Old diagrams claiming memory-only storage,
three always-active message middlewares, or inconsistent `result.data` handlers are obsolete.
