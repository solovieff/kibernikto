# Payments — Telegram Stars

Kibernikto ships a minimal Telegram Stars (`XTR`) integration in
`kibernikto/telegram/payment/payment_utils.py`, gated by `SubscriptionMiddleware` when
`SUBSCRIPTION_ENABLED=true`.

## Public API

```python
from kibernikto.telegram.payment.payment_utils import create_payment_link, check_sub

# Build an invoice link for a given price (XTR)
link = await create_payment_link(bot, price=52, descr="Make a token payment to continue!")

# Check whether `user_id` has an active subscription
active = await check_sub(user_id=12345, bot=bot)
```

## `create_payment_link`

```python
async def create_payment_link(bot: Bot, price=1,
                              descr='Make a symbolic payment to enjoy my power!') -> str:
    payment_link = await bot.create_invoice_link(
        title="Kibernikto",
        description=descr,
        payload='subscription_payload',
        currency='XTR',
        prices=[LabeledPrice(label="Subscription", amount=price)],
        provider_token='',
        subscription_period=DEFAULT_SUBSCRIPTION_PERIOD,
    )
    return payment_link
```

### Key points

- `currency='XTR'` is **Telegram Stars**. Stars are denominated in whole units (1 XTR = 1 Star),
  no fractional amounts.
- `provider_token=''` is correct for Stars — Stars don't use a payment provider token.
- `subscription_period=DEFAULT_SUBSCRIPTION_PERIOD` is 30 days (`2592000` seconds). Telegram charges
  the user every `subscription_period` until cancelled.
- `payload='subscription_payload'` is a string passed back to the bot on every renewal. Treat it as
  an opaque identifier — the current code does not parse it.

To change the duration, edit `DEFAULT_SUBSCRIPTION_PERIOD` in
`kibernikto/telegram/payment/payment_utils.py`. Telegram accepts `subscription_period` between
`30` and `2592000` seconds, so the practical range is 30 seconds (testing) to 30 days (production).

## `check_sub`

```python
async def check_sub(user_id, bot: Bot):
    data = await bot.get_star_transactions()
    transactions: List[StarTransaction] = data.transactions
    last_transaction = max(
        (t for t in transactions
         if t.source is not None
         and t.source.user.id == user_id
         and t.source.subscription_period == DEFAULT_SUBSCRIPTION_PERIOD),
        key=lambda t: t.date,
        default=None,
    )
    if last_transaction:
        transaction_date = last_transaction.date
        now = datetime.now(transaction_date.tzinfo)
        time_since_transaction = now - transaction_date
        if time_since_transaction.total_seconds() <= DEFAULT_SUBSCRIPTION_PERIOD:
            return True
        else:
            print(f"Subscription is not active for {user_id}")
            return False
    else:
        print("Subscription is not active.")
        return False
```

### Caveats

- `bot.get_star_transactions()` returns the **last N transactions** (Telegram limits this; check
  the Bot API docs for the current page size). For heavy users the active subscription may not be
  in the most recent page. The current implementation does not paginate.
- The `print(...)` calls are debug noise — they should be `logger.info(...)` or removed. The two
  print lines are the only `print` statements in the production code path.
- The check uses the **transaction date**, not the bot's notion of "when the subscription started".
  Telegram automatically renews the subscription, so the most recent matching transaction is the
  authoritative answer for "is this user subscribed right now?".
- A subscription cancelled mid-period may still appear in `transactions` until the period expires;
  `check_sub` will still return `True` until the `DEFAULT_SUBSCRIPTION_PERIOD` elapses. There is no
  way to detect an early cancellation via `get_star_transactions()` alone.

## Subscription keyboard

`SubscriptionMiddleware.get_payment_keyboard(bot)` builds a one-row, three-column
`InlineKeyboardMarkup` with prices from `SUBSCRIPTION_SETTINGS`:

| Button label | Reads from |
|---|---|
| `\|\|` | `SUBSCRIPTION_BASE_PRICE_STARS` (default `52`) |
| `\|\|\|` | `SUBSCRIPTION_TRIAL_CREDITS` (default `247`) |
| `\|\|\|\|\|` | `SUBSCRIPTION_RICH_CREDITS` (default `390`) |

Each is a `url=` button pointing at the corresponding `create_payment_link` invoice. The labels are
deliberately cryptic — change them to user-friendly names like `"Basic"`, `"Pro"`, `"Max"` when you
brand the bot.

The "ACCESS RESTRICTED: MORTAL DETECTED" message is hard-coded in
`SubscriptionMiddleware.__call__`. Tone it down for production use.

## End-to-end flow

```
1. Private user sends a message
        │
        ▼
2. ServiceMiddleware → forward to service group
3. ErrorsMiddleware   → (no-op unless exception)
4. FirewallMiddleware → admin_or_public check
5. SubscriptionMiddleware
        │
        ├─ can_skip? → proceed
        ├─ can_skip? false → check_sub(user_id, bot)
        │       │
        │       ├─ active    → proceed
        │       └─ inactive  → send payment keyboard + return None (handler is short-circuited)
        │
        ▼
6. conversation_router → handle_private_message
        │
        ▼
7. kibernikto_agent.run(user_message, chat_id=message.chat.id)
```

When the user clicks a payment button, Telegram opens the invoice in their client. On payment,
Telegram delivers a `Message` with `successful_payment` populated to the bot. `can_skip_subscription`
returns `True` for that message, so the post-payment notification reaches the handler — but the
current handlers do **not** act on `successful_payment` (no `elif message.successful_payment` branch).
The user is free to type their next message; `check_sub` will now return `True`.

### To add a `successful_payment` confirmation message

```python
# in handle_private_message, before the preprocess step:
if message.successful_payment:
    await message.answer("Thanks for subscribing! 🌟 Send me anything to start chatting.")
    return
```

Place this in `kibernikto/telegram/handlers/conversation.py`.

## Testing payments locally

Telegram Stars require a real bot in production. For local development:

1. Create a test bot with `@BotFather`, use `@BotFather → /mybots → Payments → Test Stars`.
2. Set `SUBSCRIPTION_ENABLED=true` and `SUBSCRIPTION_BASE_PRICE_STARS=1` for cheap testing.
3. Use `bot.create_invoice_link` to print a link, click it in your test client.
4. The post-payment message will have `successful_payment` populated.

There is no mock for `bot.get_star_transactions` in the codebase — for unit tests, monkey-patch
`check_sub` to return a fixed value:

```python
import kibernikto.telegram.payment.payment_utils as p
p.check_sub = lambda user_id, bot: asyncio.sleep(0, result=True)
```
