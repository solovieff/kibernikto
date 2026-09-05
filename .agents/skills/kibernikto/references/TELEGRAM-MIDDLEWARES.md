# Telegram middlewares

Registration: `kibernikto/telegram/agent/telegram_app.py`.
Implementations: `kibernikto/telegram/middleware/`.

## Observer-specific order

Do not describe error reporting as a message wrapper. Current registration is:

| Observer | Outer-to-inner registration |
|---|---|
| `dispatcher.message` | Peer → optional Service → Firewall → optional Subscription |
| `dispatcher.edited_message` | Peer (context only; no reply acceptance) → Firewall |
| `dispatcher.error` | optional Errors middleware |

`TelegramApp.__init__` always installs PeerMiddleware and peer-hub shutdown.
`from_agent` then calls `apply_if_needed` on Service, Errors, Firewall, Subscription.
There is no runner module. New middleware must choose the correct observer(s), not
just append to an imaginary shared chain.

## PeerMiddleware

Source: `kibernikto/telegram/middleware/middleware_peer.py`.
For normal messages it lets `PeerHub.accept(bot.id, message)` consume only correlated
private responses (or retained late/duplicate IDs), bypassing service forwarding,
firewall, subscriptions and conversation handling. For other updates it binds the
app hub in a context variable and restores it in `finally`. Edited-message middleware
binds context but never completes peer calls. See [Peers](TELEGRAM-PEERS.md).

## ServiceMiddleware

Source: `kibernikto/telegram/middleware/middleware_service.py`.
Installed on normal messages only when `TG_SERVICE_GROUP_ID is not None`.
Construction requires a truthy group ID. For private messages it schedules a
background forward; `_forward` **skips admins** and catches/logs forwarding errors.
It is before the firewall, so non-admin input can be forwarded even if later denied.

The historical `or 1 == 1` debug expression is absent. Do not preserve or reintroduce
it based on stale instructions, and don't change this implementation during a docs audit.

## ErrorsMiddleware

Defined in the same service module and enabled by the same group setting. It is
registered on `dispatcher.error.outer_middleware`, receives an `ErrorEvent`, calls
the downstream handler first, then schedules a service-group report when the update
contains an extractable message. It does not provide a guaranteed user-facing error
reply, an unconditional catch-all, or a complete peer retry/recovery policy.

## FirewallMiddleware

Source: `kibernikto/telegram/middleware/middleware_firewall.py`.
Always installed on both normal and edited messages, even when public.

| Input | Allowed when | Denial |
|---|---|---|
| Private | `TG_PUBLIC` or sender equals `MASTER_ID` or is in `MASTER_IDS` | uses reply helper for access-denied text |
| Other chats | no/empty `FRIEND_GROUP_IDS`, or chat ID in that list | silent drop |

`TG_PRIVILEGED_USERS` is not consulted. Admin detection lives in
`kibernikto/telegram/utils/permissions.py`; it assumes a sender is present.
A new private bot request needs both peer opt-in and normal firewall access.
A correlated response needs neither duplicate peer opt-in nor an admin grant.

## SubscriptionMiddleware

Source: `kibernikto/telegram/middleware/middleware_subscription.py`.
Enabled on normal messages only by `SUBSCRIPTION_ENABLED`. Skips successful-payment
messages, slash commands and non-private chats. There is **no admin exemption**.
Other private messages call `check_sub(message.chat.id, bot)`; inactive accounts get
three invoice-link buttons and no model invocation. `PROMO_FREE_PROB` is unused.
Peer opt-in does not bypass this check for new requests. Edited messages are not
paywalled by this registration; document this limit, don't assume equivalence.

## Event extraction and verification

`get_event_message` in `kibernikto/telegram/middleware/utils.py` accepts a direct
`Message` or an `Update` containing `message`/`edited_message`. It is not a dict
parser and does not extract every callback/payment update type.

Test observer order with an actual Dispatcher and fake Bot methods. Assert correlated
answers never reach service/access handlers; separately test denied unsolicited
requests and edited human delegation. Never claim full error handling from happy-path
or generic exception-containment tests alone.
