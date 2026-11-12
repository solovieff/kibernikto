# VkusVill agent (phase «a») — design

Date: 2026-11-12
Status: awaiting review

## Goal

Add a VkusVill shopping agent to the kibernikto repository that talks to the official
VkusVill MCP server, and make it runnable as the Telegram bot (`main.py --vkusvill`) so the
whole flow is verified through the existing transport, history and persona machinery.

Phase «b» — exposing the agent to external kibernikto deployments with per-user login
(Telegram button + website) — is explicitly out of scope here, but the module boundaries below
are chosen so that per-user tokens can be added without rewriting the agent.

## Verified facts (probed live, 2026-11-12)

- Endpoint `https://mcp.vkusvill.ru/mcp`, Streamable HTTP, StreamableHttpTransport works,
  `protocolVersion` negotiated 2025-03-26.
- 11 tools: `vkusvill_products_search`, `vkusvill_product_details`, `vkusvill_product_analogs`,
  `vkusvill_product_barcode`, `vkusvill_shops`, `vkusvill_recipes`, `vkusvill_products_discount`,
  `vkusvill_cart_link_create`, `vkusvill_orders_history`, `vkusvill_product_lp`,
  `vkusvill_discounts_personal`.
- Anonymous calls work for the catalog tools. Personalized tools require OAuth 2.0 + PKCE;
  protected-resource metadata advertises scopes `catalog.search`, `purchase_history.read`,
  `discounts.view`, `recommendations.personalized`.
- There is **no order-placement tool**. The terminal action is `vkusvill_cart_link_create`,
  which returns `https://vkusvill.ru/mobile?basket&share=<id>`; the human opens it and confirms.
  The agent must never claim it has placed an order.
- Tool responses are JSON text `{"ok": true, "data": ...}` or `{"ok": false, "error": {...}}`.
  `vkusvill_products_search` returns `data.items[]` with `id`, `name`, `price.current`,
  `rating.average`, `url`; `vkusvill_cart_link_create` takes `products: [{"id": int, "q": float}]`.
- pydantic-ai 2.55 `MCPToolset` + `routerai:deepseek/deepseek-v4.1-flash` produced a real
  share link end-to-end: model → `vkusvill_products_search` → `vkusvill_cart_link_create` → link.
- `Agent.run` enters MCP toolsets itself; no `async with agent` needed around the polling loop.
- `fastmcp.client.auth.OAuth` supports static `client_id`/`client_secret` (no dynamic
  registration), a local callback server, and `token_storage`. `key_value.aio.stores.filetree.
  FileTreeStore` provides persistent storage without adding a dependency (`DiskStore` needs an
  extra package — not used).

## Approach

**Chosen: thin MCP passthrough.** The agent receives all 11 tools directly via `MCPToolset`.
Persona and behaviour live in text instructions. New upstream tools appear automatically.

Rejected:

- *Wrapper adapter per tool* — a mountain of code, new upstream tools must be hand-wired, and
  the JSON payloads are already compact enough for the model.
- *Sub-agent delegation* — an extra model round trip per request, pointless for a single-domain
  agent the user talks to directly.

## Architecture

New package `kibernikto/ai/agent/vkusvill/`:

```
config.py   VkusvillSettings (env prefix VKUSVILL_) + VKUSVILL_SETTINGS singleton
mcp.py      build_vkusvill_toolset() -> MCPToolset, auth chosen by AUTH_MODE
prompts.py  VKUSVILL_INSTRUCTIONS — identity + shopping contract
agent.py    build_vkusvill_agent(...) -> Agent[TelegramDeps]
__init__.py relative re-exports only (no __all__)
```

### `config.py`

`VkusvillSettings(BaseSettings)`, `env_prefix='VKUSVILL_'`:

| Field | Default | Meaning |
|---|---|---|
| `MCP_URL` | `https://mcp.vkusvill.ru/mcp` | MCP endpoint |
| `NAME` | `vkusvill` | agent name in logs, summaries and attribution headers (ASCII — it rides an HTTP header) |
| `MODEL_NAME` | unset | provider-prefixed model; unset → `AGENT_KIBERNIKTO_MODEL_NAME` |
| `AUTH_MODE` | `anonymous` | `anonymous` \| `oauth` |
| `OAUTH_CLIENT_ID` | unset | from the VkusVill registration email |
| `OAUTH_CLIENT_SECRET` | unset | same |
| `OAUTH_SCOPES` | all four advertised scopes | JSON list, like `AGENT_KIBERNIKTO_FALLBACK_MODELS` |
| `OAUTH_CALLBACK_PORT` | `8765` | local callback port, must match the registered redirect URI |
| `OAUTH_CALLBACK_HOST` | `localhost` | callback host |
| `OAUTH_TOKEN_DIR` | `{APP_STORAGE_FILESTORE_LOCATION}/vkusvill-oauth` | persistent token store directory |

`@model_validator(mode='after')` raises when `AUTH_MODE='oauth'` and either credential is
missing — same fail-fast style as `StorageSettings`.

### `mcp.py`

```python
def build_vkusvill_toolset(settings: VkusvillSettings = VKUSVILL_SETTINGS) -> MCPToolset[object]
```

- `anonymous` → `MCPToolset(settings.MCP_URL)`.
- `oauth` → `MCPToolset(settings.MCP_URL, auth=OAuth(client_id=..., client_secret=...,
  scopes=..., callback_port=..., callback_host=...,
  token_storage=FileTreeStore(data_directory=<OAUTH_TOKEN_DIR>)))`, cast to the declared auth type.
- Directory is created on first use; nothing touches the network at import time.

### `prompts.py`

`VKUSVILL_INSTRUCTIONS` states, in Russian:

1. Identity: assistant of the VkusVill online store.
2. Only report products returned by tools; never invent names, prices or availability.
3. On a shopping request offer up to three carts — «Выгодно» (cheapest), «Любимое» (best
   rating), «Лайт» (fewest calories) — picked from real search results.
4. Always finish a shopping flow with the `share` link from `vkusvill_cart_link_create` plus the
   disclaimer that prices, availability and composition must be checked on the product pages.
5. Never claim an order was placed: the link must be opened and confirmed by the human.
6. Prices in RUB, quantities in the tool's units (`q` is a number, 0.01–40).

### `agent.py`

```python
def build_vkusvill_agent(*, history_storage: HistoryStorage | None = history_storage,
                         toolset: AbstractToolset | None = None,
                         **kwargs) -> Agent[TelegramDeps]
```

- Model: `infer_kibernikto_model(VKUSVILL_SETTINGS.MODEL_NAME)` when set, otherwise the library
  default; `**kwargs` still overrides.
- Delegates to `build_telegram_agent(..., name=VKUSVILL_SETTINGS.NAME, persona=False,
  instructions=VKUSVILL_INSTRUCTIONS, toolsets=[toolset])`, so `TelegramCapability`,
  `ConversationHistory`, reactions and media handling stay identical to the default agent.
- `persona=False` — the generic kibernikto persona must not leak into the shop assistant;
  `PersonaCapability` still contributes the current-date instruction.

## Run path

`kibernikto/cmd/__start.py` gains `--vkusvill`. With the flag:

```python
from kibernikto.ai.agent.vkusvill import build_vkusvill_agent
bridge = TelegramBridge(build_vkusvill_agent())
print_agent_summary('vkusvill')
```

Everything else (storage validation, `TelegramApp.from_bridge`, polling) is unchanged, and the
flag is parsed before any runtime import so `--help` stays offline and credential-free.

## OAuth lifecycle

1. User registers a client at `https://vkusvill.ru/oauth/registration/`; the email carries
   `client_id`, `client_secret`, `redirect_uri`, `scope`.
2. `VKUSVILL_AUTH_MODE=oauth` plus credentials in `.env`.
3. First run opens the browser at the authorization URL; the local callback collects the code,
   PKCE exchanges it for a 24h JWT, and the token is written to `OAUTH_TOKEN_DIR`.
4. Later runs reuse the stored token; a 401 triggers the flow again.
5. Anonymous mode never touches any of this and stays the default, so the agent is usable
   without credentials.

## Error handling

- Upstream `{"ok": false, "error": {...}}` is returned to the model as tool output; instructions
  tell it to report the failure in plain words and never fabricate products.
- A tool error never kills the Telegram handler — pydantic-ai retry/messages handling stays as is.
- Network failures surface through the existing agent error path; no custom retry layer.

## Testing

Offline (`tests/test_vkusvill_agent.py`, `unittest`, no network):

- settings defaults; `AUTH_MODE='oauth'` without credentials raises; scopes default to all four.
- `build_vkusvill_toolset()` anonymous → `MCPToolset` pointing at `MCP_URL`; oauth → an `OAuth`
  auth object carrying the configured credentials (constructed offline).
- `build_vkusvill_agent()` with an injected stub toolset: name, `instructions` (identity,
  share-link rule, no-order disclaimer), `toolsets` wiring, `persona=False`.
- CLI: extend `tests/test_cli_startup.py` so `--help` lists `--vkusvill` and still imports no
  runtime configuration.
- `FileTreeStore` smoke test (write/read a token-shaped value) using `tmp_path`.

Live gate (manual, by the user): `main.py --vkusvill` against the test bot, prompt
«собери корзину: круассан, сырники, сметана» → real share link → open on vkusvill.ru.

## Docs to update

- `AGENTS.md` architecture block — new `kibernikto/ai/agent/vkusvill/` layer.
- `.agents/skills/kibernikto/SKILL.md` source map + `check_docs.py --tests` must stay green.
- `deploy/tg_bots/kibernikto/kibernikto.env` — commented `VKUSVILL_*` block.
- `examples/vkusvill_agent.py` — library usage without Telegram.

## Risks

- The MCP server is labelled experimental; tool schemas may shift. Passthrough means no code
  changes are needed for additive changes.
- OAuth redirect registration may reject `localhost`; the callback host/port are configurable.
- Personalized tools error anonymously, so instructions must steer the model to the public tools
  when `AUTH_MODE=anonymous`.

## Out of scope (phase «b»)

Per-user OAuth (login button in Telegram and on the website), token custody per kibernikto user,
revocation, and any order confirmation flow beyond the share link.
