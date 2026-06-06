# Telegram Handlers

Source: `kibernikto/telegram/handlers/`

## Router Layout

Two `Router` objects, both included in `runner.init()`:

| Router | Module | Handles |
|---|---|---|
| `commands_router` | `handlers/commands.py` | `/start`, `/help` — replies with bot identity text |
| `conversation_router` | `handlers/conversation.py` | Private messages, group messages, edited messages |

## Conversation Router

Three handlers on `conversation_router`:

| Handler | Filter | Notes |
|---|---|---|
| `private_message_handler` | `F.chat.type == "private"` | All private messages → `_process_and_reply` |
| `edited_message_handler` | any edited message | Same flow as private |
| `group_message_handler` | group/supergroup, `should_react(message)` | Only fires if bot is mentioned or `TG_REACTION_CALLS` matched |

**`_process_and_reply(message)`** is the shared helper that all three call:
1. Sends a "typing…" action
2. Calls `kibernikto_telegram_agent.process_message(message)` → `AgentRunResult | None`
3. If result is not `None`, calls `kibernikto_telegram_agent.reply_to(message, result)`

The handler always reads the **current module-level `kibernikto_telegram_agent`** (not a snapshot
at import time) so that `set_telegram_agent(my_agent)` takes effect without restarting.

## Swapping the Agent

```python
from kibernikto.telegram.agent import set_telegram_agent, TelegramAgent

class MyAgent(TelegramAgent):
    ...

set_telegram_agent(MyAgent(...))  # call before dispatcher starts
```

After this, all three conversation handlers dispatch to `MyAgent`.

## Known Quirks

- **`result.output` vs `result.data`**: private handler uses `result.output` (the raw text string),
  group/edited handlers use `result.data`. They're equivalent when `output_type` is the default
  (`str`) — but if you set a structured `output_type`, group replies will send the model object, not
  the text. Keep them consistent if you change `output_type`.
- **`should_react`** in `kibernikto/telegram/utils/permissions.py` has a broken import
  (`from telegram.utils.conversation import ...` instead of `from kibernikto.telegram...`). It only
  manifests in groups with replies where the import path resolves to a wrong package.
