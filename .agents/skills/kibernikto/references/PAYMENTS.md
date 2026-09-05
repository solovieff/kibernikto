# Payments: Telegram Stars

Sources: `kibernikto/telegram/payment/payment_utils.py`,
`kibernikto/telegram/middleware/middleware_subscription.py`.

## Implemented flow

1. Optional SubscriptionMiddleware receives a normal message after the firewall.
2. Successful-payment messages, slash commands and non-private chats bypass the check.
   Admin status alone does not bypass it.
3. For other private messages, `check_sub(message.chat.id, bot)` requests
   `bot.get_star_transactions()` and finds the latest matching source user with the
   fixed subscription period. It accepts a transaction within that period.
4. If inactive, `get_payment_keyboard(bot)` generates three invoice links through
   `create_payment_link` and sends an access-restricted message; no agent run occurs.

## Real APIs

| Function | Contract |
|---|---|
| `create_payment_link(bot, price=1, descr=...)` | `bot.create_invoice_link`, XTR currency, empty provider token, one LabeledPrice, fixed subscription payload and period |
| `check_sub(user_id, bot)` | reads Telegram Star transactions, selects latest matching source and tests age |
| `SubscriptionMiddleware.get_payment_keyboard(bot)` | three URL buttons using BASE_PRICE_STARS, TRIAL_CREDITS and RICH_CREDITS as invoice amounts |

`DEFAULT_SUBSCRIPTION_PERIOD = 2592000` is the intentionally fixed 30-day period.
There is no configurable `SUBSCRIPTION_PERIOD` or `SUBSCRIPTION_PRICE` field.
See [Configuration](CONFIGURATION.md#subscription) for actual field names and defaults.

## Storage and incomplete integration

There is **no process-local subscription dict** and no application subscription DB.
The implementation asks Telegram on every checked message. It only examines the
returned transaction page: no pagination, authoritative entitlement ledger, refund
reconciliation or comprehensive source-type validation is implemented here.

The current app/routers do **not** register dedicated pre-checkout approval or
successful-payment fulfillment handlers. The middleware's successful-payment skip
is not a fulfillment implementation. Old references to `send_subscription_invoice`,
`handle_pre_checkout`, `handle_successful_payment` or `has_active_subscription` were
invented/stale APIs, not functions available to import.

`SUBSCRIPTION_PROMO_FREE_PROB` is declared but unused. Agent credit balances in
`ConversationInfo` and `KiberniktoExtended` are a separate mechanism; no payment-driven
credit top-up is wired. Do not describe billing as end-to-end complete.

## Verification

Use a fake Bot for transaction lookup and invoice creation. Assert current skip
conditions, no admin-only exemption, the three actual invoice prices and fixed period.
Changes to payment completion need explicit handler tests and authorized live payment
verification; do not create invoices or charge Stars during a docs-only audit.
