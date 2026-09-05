# Telegram handlers

Sources: `kibernikto/telegram/handlers/conversation.py`,
`kibernikto/telegram/handlers/commands.py`.

## Router registration

`TelegramApp.from_agent` in `kibernikto/telegram/agent/telegram_app.py` includes
`commands_router` before `conversation_router`. Commands handle `/start` and `/help`
with static text; they are not the identity-instruction subsystem or a payment router.
Module-level Router instances should not be attached to multiple Dispatchers in one
process without a deliberate routing redesign.

| Handler | Filters and behavior |
|---|---|
| `handle_private_message` | private, text and caption not slash-prefixed |
| `handle_edited_message` | edited **private** messages, same slash exclusions |
| `handle_group_message` | group/supergroup, slash exclusions, then `should_react` |

There is no edited-group conversation handler. `_process_and_reply` resolves
`_agent_module.kibernikto_telegram_agent` each time, sends one typing action, awaits
`process_message`, then calls `reply_to` (which handles None). It does not inspect
`result.data` or refresh a typing loop.

## Agent replacement

```python
from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent, set_telegram_agent
from kibernikto.ai.agent import kibernikto_agent

class MyAgent(TelegramAgent):
    pass

agent = MyAgent(
    model=kibernikto_agent.model,
    model_settings=kibernikto_agent.model_settings,
    name="my-agent",
)
previous = set_telegram_agent(agent)
app = agent.to_telegram()
# Authorized live execution only: app.run_polling()
```

`set_telegram_agent` returns the previous agent. `to_telegram()` and
`TelegramApp.from_agent(agent)` do **not** perform registration; omitting the setter
leaves handlers pointing to the old agent. Register before polling, rather than
relying on a copied re-exported singleton name.

Customize `pre_processor` (constructor or property), `build_deps(message)`,
`process_message(message)`, or `reply_to(message, result)`. Keep
`await super().build_deps(message)` when extending the chat-context logic.
The actual `process_message` return is `AgentRunResult | str | None`; current model
exceptions become strings, while preprocessing/dependency errors can escape to aiogram.
Do not label this general error conversion a complete error policy.

## Groups and bots

`should_react` uses runtime `bot_me` from app startup and the correctly qualified
conversation utility import. It requires text/caption-like content and reacts to a
reply to this bot, configured substrings, full bot name or `@username` (case-insensitive).
Tests invoking it directly must establish bot identity first.

Group input gets author and local-time annotations. Human replies are anchored;
group bot output is flat (no reply chain), and a positive `BOT_MESSAGE_DELAY` enables
a randomized delay. Keep these loop-breaking rules.

Private bot input is accepted as a **new request** only when the sender is in
`TG_PEER_IDS` and there is no `reply_to_message`; ordinary access rules still apply.
Expected replies are consumed by PeerMiddleware before handlers. Edited updates get
hub context for human-initiated delegation but are not accepted as completed peer replies.
See [Peers](TELEGRAM-PEERS.md).

## Superseded notes

The transport package no longer exports the agent class/setter. Import from
`kibernikto.ai.agent.telegram.telegram_agent` (or the verified top-level agent exports).
Old descriptions of broken `should_react` imports or private/group `output`/`data`
inconsistency do not match the current handlers.
