# Payments: Telegram Stars

Sources: `kibernikto/telegram/payment/payment_utils.py`,
`kibernikto/telegram/middleware/middleware_subscription.py`.

## Implemented flow

1. Optional SubscriptionMiddleware receives a normal message after the firewall.
2. Successful-payment messages, slash commands and non-private chats bypass the check.
   Admin status alone does not bypass it.
3. For other private messages, `check_sub(message.chat.id, bot)` requests
   `bot.get_star_transactions(offset=..., limit=100)` across all pages and finds the
   latest non-refunded invoice payment for that user, payload and fixed subscription
   period. Non-user sources are ignored. Future-dated and expired payments are rejected.
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
The implementation asks Telegram on every checked message. Pagination and refund-ID
exclusion are implemented, but there is no durable entitlement ledger or snapshot
isolation while pages change. Large transaction histories increase lookup latency.

`kibernikto/telegram/handlers/payments.py` registers `handle_pre_checkout` and
`handle_successful_payment`. Checkout validates enabled billing, XTR, the payload
and one of the three current configured amounts. Successful payments are consumed
before conversations and acknowledged without calling an LLM. Invoice links created
before price changes may be rejected; request a new link. Acknowledgement is not a
durable fulfillment ledger or credit top-up. The APIs `send_subscription_invoice`
and `has_active_subscription` do not exist.

`SUBSCRIPTION_PROMO_FREE_PROB` is declared but unused. Agent credit balances in
`ConversationInfo` and `KiberniktoExtended` are a separate mechanism; no payment-driven
credit top-up is wired. Do not describe billing as end-to-end complete.

## Verification

Use a fake Bot for transaction lookup and invoice creation. Assert current skip
conditions, no admin-only exemption, the three actual invoice prices and fixed period.
Changes to payment completion need explicit handler tests and authorized live payment
verification; do not create invoices or charge Stars during a docs-only audit.
