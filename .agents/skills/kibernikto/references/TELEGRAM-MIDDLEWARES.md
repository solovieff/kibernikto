# Telegram Middlewares

Source: `kibernikto/telegram/middleware/`

## Registration Order

Middlewares are applied **outer-to-inner** in this order (defined in `runner.init()`):

```
ServiceMiddleware → ErrorsMiddleware → FirewallMiddleware → SubscriptionMiddleware
```

Each middleware implements `apply_if_needed(dispatcher)` as a `@staticmethod` that conditionally
registers itself. Adding a new middleware = implement that method + append call in `runner.init()`.

`get_event_message(event_data)` in `middleware/utils.py` extracts the `Message` from any aiogram
update type (message, edited_message, callback_query, etc.).

## ServiceMiddleware (`middleware_service.py`)

**Always active.** Runs on every update.

- Logs incoming messages via Logfire
- Forwards a copy to `TG_SERVICE_GROUP_ID` if set
- `is_from_admin(message)` check used internally

> ⚠️ **Known bug**: `forward_message_service_group` contains `or 1 == 1` (marked `# FIXME DEBUG`)
> which causes **every** private message to be forwarded regardless of admin status. Fix to
> `or not is_from_admin(message)` (everyone except admin) or remove the `or 1 == 1` clause.

## ErrorsMiddleware (inline in `runner.py`)

**Always active.** Wraps handler execution in a try/except:
- Logs exceptions via Logfire
- Sends a user-facing error message to the chat
- Does **not** re-raise — updates are silently swallowed on error

## FirewallMiddleware (`middleware_firewall.py`)

Activated when `TG_PUBLIC=false` (default).

Decision table:

| Condition | Result |
|---|---|
| `TG_PUBLIC=true` | Middleware not registered — all users pass |
| User is `TG_MASTER_ID` | Always passes |
| `TG_PUBLIC=false`, unknown user | Update dropped silently |

No allowlist beyond `TG_MASTER_ID` — the bot is either fully public or master-only.

## SubscriptionMiddleware (`middleware_subscription.py`)

Activated when `SUBSCRIPTION_ENABLED=true`.

Decision table:

| Condition | Result |
|---|---|
| User is `TG_MASTER_ID` | Always passes |
| User has active Stars subscription | Passes |
| `SUBSCRIPTION_PROMO_FREE_PROB > 0` | *(declared but not yet implemented in code)* |
| No subscription | Shows payment keyboard and drops the update |

Payment keyboard is sent via `get_payment_keyboard()` which creates a Telegram Stars invoice button.
See [Payments](./PAYMENTS.md).

## `middleware/utils.py` Helpers

| Function | Purpose |
|---|---|
| `get_event_message(event_data)` | Extract `Message` from any aiogram update dict |
| `is_from_admin(message)` | Returns `True` if `message.from_user.id == TG_MASTER_ID` |
