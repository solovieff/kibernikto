# Payments (Telegram Stars)

Source: `kibernikto/telegram/payment/payment_utils.py`

## Flow

```
User message → SubscriptionMiddleware
    ├── has active subscription?  → pass through
    └── no subscription           → send invoice keyboard → drop update

User taps "Pay" → pre_checkout_query event
    → pre_checkout handler answers OK

User completes payment → successful_payment event
    → record subscription in memory (user_id → expiry timestamp)
```

## Key Functions

| Function | Purpose |
|---|---|
| `send_subscription_invoice(message)` | Sends Stars invoice via `bot.send_invoice` |
| `handle_pre_checkout(query)` | Answers pre-checkout query with `ok=True` |
| `handle_successful_payment(message)` | Records `user_id → now + SUBSCRIPTION_PERIOD` |
| `has_active_subscription(user_id)` | Checks in-memory dict for non-expired entry |
| `get_payment_keyboard()` | Returns `InlineKeyboardMarkup` with pay button |

## Storage

Subscriptions are stored in a **process-local dict** — restart clears all subscriptions. No DB layer.

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `SUBSCRIPTION_ENABLED` | `false` | Master switch |
| `SUBSCRIPTION_PRICE` | `10` | Stars amount |
| `SUBSCRIPTION_PERIOD` | `2592000` | Period in seconds; also hard-coded as `DEFAULT_SUBSCRIPTION_PERIOD` in source |

## Handler Registration

Payment handlers (`pre_checkout_query`, `successful_payment`) are registered in `runner.init()`
alongside the conversation router — not inside a middleware.
