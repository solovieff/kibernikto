# Telegram Middlewares

The dispatcher registers four middlewares via the `apply_if_needed(dispatcher)` static-method
pattern. They run as **outer** middlewares in the order below. Each one is optional — when the
relevant setting is missing, the middleware logs `💤` and skips itself.

```python
# kibernikto/telegram/runner.py
middlewares = [ServiceMiddleware, ErrorsMiddleware, FirewallMiddleware, SubscriptionMiddleware]
for middleware in middlewares:
    middleware.apply_if_needed(tg_dispatcher)
```

## Registration Order

| # | Middleware | Source | Condition |
|---|---|---|---|
| 1 | `ServiceMiddleware` | `kibernikto/telegram/middleware/middleware_service.py` | `TG_SERVICE_GROUP_ID` is set |
| 2 | `ErrorsMiddleware` | same | `TG_SERVICE_GROUP_ID` is set |
| 3 | `FirewallMiddleware` | `kibernikto/telegram/middleware/middleware_firewall.py` | always registered (no gate) |
| 4 | `SubscriptionMiddleware` | `kibernikto/telegram/middleware/middleware_subscription.py` | `SUBSCRIPTION_ENABLED=true` |

`ServiceMiddleware` and `ErrorsMiddleware` are guarded by the same env var. The `FirewallMiddleware`
is **always** registered — it falls back to the public/deny behaviour based on
`TG_PUBLIC` and `TG_MASTER_IDS`.

## `ServiceMiddleware` — forward private messages

```python
class ServiceMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.service_group_id = TELEGRAM_SETTINGS.SERVICE_GROUP_ID
        if not self.service_group_id:
            raise EnvironmentError('Telegram Service Group ID not set')

    async def __call__(self, handler, event, data):
        message = get_event_message(event)
        if message and message.chat.type == enums.ChatType.PRIVATE:
            asyncio.create_task(self.forward_message_service_group(message))
        return await handler(event, data)

    async def forward_message_service_group(self, message):
        try:
            if not is_from_admin(message) or 1 == 1:  # FIXME DEBUG
                await message.forward(chat_id=self.service_group_id)
        except Exception as e:
            logger.exception(f"failed to send service message {e}", exc_info=True)
```

**Behaviour**: every private message is forwarded to `TG_SERVICE_GROUP_ID` in the background (via
`asyncio.create_task`, so it does not block the handler). The `or 1 == 1` is a **FIXME DEBUG** —
the `if` is always true, so every private message (admin or not) is forwarded. Tighten as needed:

- Forward **only** admins: `if is_from_admin(message):`
- Forward **everyone except** admins: `if not is_from_admin(message):`
- Forward **everyone** (current behaviour): `if True:`

> ⚠️ The `FIXME DEBUG` is a real bug. Production deployments should explicitly choose the policy.

## `ErrorsMiddleware` — surface handler exceptions

```python
class ErrorsMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_message = get_event_message(event)
        if not user_message:
            return await handler(event, data)
        service_message = f"🔥🔥🔥 {user_message.from_user.username} {user_message.content_type}: {user_message.md_text} {event.exception}"
        asyncio.create_task(self.send_message_to_service_group(bot=user_message.bot, service_message=service_message))
        return await handler(event, data)
```

**Behaviour**: registered on `dispatcher.error.outer_middleware` (not `.message`). When a handler
raises, the exception reaches the dispatcher error handler — this middleware reads
`event.exception` and sends a formatted string to `TG_SERVICE_GROUP_ID`. The 🔥 emoji prefix makes
the messages easy to filter in Telegram.

The fire-and-forget `asyncio.create_task` means the error message is sent asynchronously — the
exception still propagates and the user gets the aiogram default error response.

## `FirewallMiddleware` — access control

```python
class FirewallMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        message = get_event_message(event)
        if not message:
            logger.warning(f"No message found in event: {event}")
            return None

        if message.chat.type == enums.ChatType.PRIVATE:
            if admin_or_public(message):
                return await handler(event, data)
            else:
                await reply(message, "🔑 Access is denied!")
                return None
        else:
            if group_allowed(message):
                return await handler(event, data)
            else:
                logging.warning(f"Group Access denied for {message.from_user.username} in {message.chat.title}")
                return None
```

### Decision table

| Chat type | Allowed if | Otherwise |
|---|---|---|
| `PRIVATE` | `admin_or_public(message)` (admin OR `TG_PUBLIC=true`) | Replies "🔑 Access is denied!" and returns `None` |
| `GROUP` / `SUPERGROUP` | `group_allowed(message)` (no `TG_FRIEND_GROUP_IDS` set OR chat in the list) | Logs warning, returns `None` (no reply to the group) |

The three permission helpers live in `kibernikto/telegram/utils/permissions.py`:

```python
def is_from_admin(message):
    return (
        message.from_user.id == TELEGRAM_SETTINGS.MASTER_ID
        or message.from_user.id in TELEGRAM_SETTINGS.MASTER_IDS
    )

def admin_or_public(message):
    return is_from_admin(message) or is_public()

def is_public() -> bool:
    return TELEGRAM_SETTINGS.PUBLIC

def group_allowed(message):
    if not TELEGRAM_SETTINGS.FRIEND_GROUP_IDS:
        return True
    return message.chat.id in TELEGRAM_SETTINGS.FRIEND_GROUP_IDS
```

The fourth helper, `should_react(message)`, is the **group reaction policy** — used by the
conversation handler, not the firewall. See the "Group reaction policy" section below.

### Customising access control

The most common tweaks:

- **Add a privileged user** (bypass firewall but not admin): add their ID to `TG_PRIVILEGED_USERS` and
  extend `admin_or_public` to include the check. The setting is reserved for this purpose.
- **Allow the bot to leave non-friend groups** automatically: hook into the firewall
  `return None` branch and call `await message.bot.leave_chat(message.chat.id)`.
- **Time-of-day restrictions** (e.g. only respond 9am-9pm): wrap the firewall call with a check on
  `datetime.now()`. Place it between `ErrorsMiddleware` and `FirewallMiddleware` if you want
  errors to be logged regardless.

## `SubscriptionMiddleware` — Telegram Stars paywall

```python
class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        message = get_event_message(event)
        if not message:
            return await handler(event, data)
        if self.can_skip_subscription(message=message):
            return await handler(event, data)

        bot = data['bot']
        active = await check_sub(message.chat.id, bot)

        if active:
            return await handler(event, data)
        else:
            payment_keyboard = await self.get_payment_keyboard(bot=bot)
            await message.answer(
                f"⚠️ ACCESS RESTRICTED: MORTAL DETECTED ⚠️\n"
                "To continue accessing my awe-inspiring abilities,"
                " I require a modest payment.",
                reply_markup=payment_keyboard
            )
            return None

    @staticmethod
    def can_skip_subscription(message):
        if message.successful_payment:
            return True
        if message.text and message.text.startswith("/"):
            return True
        if message.chat.type != 'private':
            logging.warning("Skipping subscription for a group!")
            return True
        return False
```

### Skip rules

| Condition | Reason |
|---|---|
| `message.successful_payment` is set | This is the post-payment notification — let it through |
| `message.text.startswith("/")` | Commands bypass the paywall (so users can read `/help`) |
| `chat.type != 'private'` | Subscriptions are enforced only in private chats (groups always get through) |

The third rule means groups are **always free**. Set `SUBSCRIPTION_ENABLED=true` only if you want
private users to pay.

> ⚠️ `can_skip_subscription` does not roll the dice for `SUBSCRIPTION_PROMO_FREE_PROB` — the
> `PROMO_FREE_PROB` setting is **declared but not read**. To implement free-trial rolling, add
> `random.randint(1, 100) > SUBSCRIPTION_SETTINGS.PROMO_FREE_PROB` to the skip list (and remove
> `return True` in that case).

### Active subscription check

`check_sub(user_id, bot)` (in `kibernikto/telegram/payment/payment_utils.py`) calls
`bot.get_star_transactions()`, finds the most recent subscription transaction by this user, and
returns `True` if the elapsed time is within `DEFAULT_SUBSCRIPTION_PERIOD` (30 days).

See [Payments](./PAYMENTS.md) for the full flow including the keyboard construction.

## `get_event_message` helper

Every middleware uses the same `get_event_message(event)` from `kibernikto/telegram/middleware/utils.py`:

```python
def get_event_message(event: TelegramObject) -> Message | None:
    if isinstance(event, Update) and event.message:
        return event.message or event.edited_message
    elif isinstance(event, Message):
        return event
    else:
        return None
```

This handles both `Update` wrappers (the aiogram v3 default) and bare `Message` events.

## Adding a New Middleware

1. Create `kibernikto/telegram/middleware/middleware_<name>.py`.
2. Subclass `aiogram.BaseMiddleware` and implement `__call__(self, handler, event, data)`.
3. Add a `@staticmethod apply_if_needed(dispatcher: Dispatcher)` that conditionally registers it
   (use `TELEGRAM_SETTINGS` / `SUBSCRIPTION_SETTINGS` to decide; log `✅` or `💤` accordingly).
4. Append the class to the `middlewares` list in `kibernikto/telegram/runner.py::init()` — order
   matters, so think about which other middlewares should run before/after yours.

### Common patterns

- **Rate limiting**: count messages per `chat_id` over a sliding window, return `None` and reply
  with a cooldown message when exceeded.
- **Logging to a database**: mirror `ServiceMiddleware` but write to Postgres/SQLite instead of
  forwarding to a group. Use `asyncio.create_task` so the handler isn't blocked.
- **Per-user model selection**: read `TELEGRAM_SETTINGS.PRIVILEGED_USERS` and inject a
  different `kibernikto_agent` override into `data` for the duration of the request.

## Known Quirks (consolidated)

- `ServiceMiddleware` `or 1 == 1` forwards everyone (`FIXME DEBUG`).
- `should_react` has a broken import (see SKILL.md main gotchas).
- `SubscriptionMiddleware.can_skip_subscription` does not roll the `PROMO_FREE_PROB` dice.
- `ErrorsMiddleware` reads `event.exception` from the dispatcher error event — it does not catch
  per-handler exceptions; aiogram's own error handler does that and the middleware just observes.
