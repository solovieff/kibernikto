# Architecture

## Package Layout

```
kibernikto/
├── config.py                    # AppSettings (APP_*)
├── ai/agent/
│   ├── __init__.py              # re-exports kibernikto_agent singleton
│   ├── utils.py                 # infer_kibernikto_model + provider helpers
│   └── core/
│       ├── kibernikto_agent.py  # KiberniktoAgent class + agent singleton
│       ├── config.py            # AgentKiberniktoSettings
│       ├── history.py           # MemoryHistoryStorage + history_storage singleton
│       ├── deps.py              # KiberniktoDeps (attachments side-channel)
│       └── image.py             # generate_image helper
└── telegram/
    ├── config.py                # TelegramSettings (TG_*)
    ├── runner.py                # init() dispatcher + run_sync() entry
    ├── agent/
    │   └── telegram_agent.py    # TelegramAgent + TelegramDeps + kibernikto_telegram_agent
    ├── handlers/
    │   ├── commands.py          # commands_router: /start /help
    │   └── conversation.py      # conversation_router: private/group/edited
    ├── middleware/
    │   ├── middleware_service.py    # ServiceMiddleware
    │   ├── middleware_firewall.py   # FirewallMiddleware
    │   ├── middleware_subscription.py # SubscriptionMiddleware
    │   └── utils.py             # get_event_message, is_from_admin
    ├── pre_processors/
    │   ├── __init__.py          # TelegramMessagePreprocessor base
    │   └── _default.py          # DefaultTelegramMessagePreprocessor + PreprocessorSettings
    ├── payment/
    │   └── payment_utils.py     # Stars invoice / pre-checkout / subscription helpers
    └── utils/
        ├── conversation.py      # reply() — chunked Markdown send
        └── permissions.py       # should_react, is_reply, get_message_text
```

## Three Layers

```
CLI / main.py
    └── kibernikto.cmd.__start:start()
            └── kibernikto.telegram.runner:run_sync()
                    ├── init()  — builds Dispatcher, wires routers + middlewares
                    └── dp.run_polling(bot)
```

| Layer | Responsibility |
|---|---|
| `kibernikto.ai.agent` | LLM calls, history, model routing — no Telegram |
| `kibernikto.telegram.agent` | Telegram ↔ agent bridge (`process_message`, `reply_to`) |
| `kibernikto.telegram.*` | Dispatcher, handlers, middlewares, preprocessors, payments |

## Request Lifecycle

```
Telegram Update
  → ServiceMiddleware   (log, forward to service group)
  → ErrorsMiddleware    (catch & report exceptions)
  → FirewallMiddleware  (allowlist / publicness check)
  → SubscriptionMiddleware (Stars paywall if enabled)
  → conversation_router / commands_router
      → _process_and_reply(message)
          → TelegramMessagePreprocessor().process_tg_message(message)  → list[UserContent]
          → kibernikto_telegram_agent.process_message(message)
              → KiberniktoAgent.run(user_content, chat_id=chat_id)
                  → history_storage.get_conversation(chat_id)
                  → pydantic_ai.Agent.run(...)
                  → history_storage.add_messages(chat_id, new_messages)
          → kibernikto_telegram_agent.reply_to(message, result)
              → reply(message, text, ...)  — chunked Markdown send
```

## Singleton Chain

| Singleton | Module | Built from |
|---|---|---|
| `kibernikto_agent` | `kibernikto.ai.agent` | `AGENT_KIBERNIKTO_SETTINGS` |
| `kibernikto_telegram_agent` | `kibernikto.telegram.agent` | same settings, wraps `kibernikto_agent` pattern |
| `history_storage` | `kibernikto.ai.agent.core.history` | process-local `defaultdict` |

## Settings Surface

| Class | Prefix | Module |
|---|---|---|
| `AppSettings` | `APP_` | `kibernikto.config` |
| `AgentKiberniktoSettings` | `AGENT_KIBERNIKTO_` | `kibernikto.ai.agent.core.config` |
| `TelegramSettings` | `TG_` | `kibernikto.telegram.config` |
| `SubscriptionSettings` | `SUBSCRIPTION_` | `kibernikto.telegram.middleware.middleware_subscription` |
| `PreprocessorSettings` | `TRANSCRIBE_` | `kibernikto.telegram.pre_processors._default` |

## Class Hierarchy

```
pydantic_ai.Agent
    └── KiberniktoAgent          — adds chat_id history, binary attachment materialisation
            └── TelegramAgent    — adds process_message(), reply_to(), TelegramDeps
```

`TelegramDeps` inherits `KiberniktoDeps` (attachments list, extra dict) and adds `message: Message | None`.
