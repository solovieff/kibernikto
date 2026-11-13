# Server layout

Copy this folder to the server as is. One folder in `tg_bots/` per bot; the folder name is the bot, service, container and image name.

```
scripts/                 shared: rebuild, update, start, stop, logs; known_hosts = pinned GitHub host keys
tg_bots/kibernikto/
  kibernikto.env         bot config (or .env)
  deploy.conf            REPO= (required), BRANCH= (default main)
  Dockerfile             image recipe: clones REPO, uv sync, state in /data
  github.key             deploy key of REPO, read-only, no passphrase (add it yourself, never commit)
  data/                  created on first run: history, credits, media, sqlite
```

New bot: copy `tg_bots/kibernikto` to `tg_bots/<bot>`, rename the env file to `<bot>.env`, set `REPO`, add `github.key`.

As root:

```shell
scripts/rebuild.sh -b <bot>   # build from git and (re)start as <bot>.service
scripts/update.sh             # rebuild every bot whose branch has new commits (cron-friendly)
scripts/log.sh <bot>          # follow output; start.sh / stop.sh / save_todays_log.sh / bash_container.sh
```

Inside `tg_bots/<bot>/` the bot argument can be omitted.

Moving an existing bot whose state is in an anonymous volume: copy it out before the first `rebuild.sh`,
`podman cp <bot>:/data/. tg_bots/<bot>/data/`.

## Travel expert

`AGENT_TRAVEL_ENABLED=true` enables one travel coordinator in the multi-agent bot. It can delegate to
Tutu (hotels, flights, rail, buses and commuter trains) and Kiwi (flight search). The bundled deployment
example enables it; the library default is disabled. Access is limited to private chats with credits strictly
above `AGENT_TRAVEL_MIN_CREDITS` (default 2000; zero disables the credit minimum but not the private-chat rule).
The coordinator, Tutu and Kiwi models can be set independently with `AGENT_TRAVEL_MODEL_NAME`,
`AGENT_TRAVEL_TUTU_MODEL_NAME` and `AGENT_KIWI_MODEL_NAME`; when unset, each uses the default agent model.
`AGENT_TRAVEL_TUTU_MCP_URL` and `AGENT_KIWI_MCP_URL` override the endpoints. `AGENT_TRAVEL_MAX_TOOL_CALLS`
limits the coordinator and Tutu runs; `AGENT_KIWI_MAX_TOOL_CALLS` limits the Kiwi run. These are per-delegation
limits, not a global cap; child usage is forwarded to the parent. No API keys are required by the MCP endpoints.
The maximum model output defaults to 8192 tokens for each travel agent. Override the coordinator, Tutu,
and Kiwi independently with `AGENT_TRAVEL_MODEL_MAX_TOKENS`, `AGENT_TRAVEL_TUTU_MODEL_MAX_TOKENS`,
and `AGENT_KIWI_MODEL_MAX_TOKENS`, respectively.

Tutu passenger registration is excluded from the toolset; search and checkout-link generation do not book or
pay. Travelers complete checkout themselves. Search criteria go to the selected provider. Prices and
availability may change; inspect baggage and cancellation terms before purchasing.

## Business expert

Set `AGENT_BUSINESS_DADATA_TOKEN` to the DaData API key and secret key joined by a colon in the bot's
private runtime environment. Never commit the value or put it in the MCP URL. The agent is available only when
both keys are present and the token is well-formed; a malformed token disables it and emits a warning without
printing the token. `AGENT_BUSINESS_MIN_CREDITS` defaults to 2000 (strictly greater, private chats only;
zero removes the minimum but keeps the private-chat restriction). `AGENT_BUSINESS_MODEL_NAME` is optional,
and `AGENT_BUSINESS_MAX_TOOL_CALLS` defaults to 20. The official MCP provides company and entrepreneur lookup,
company lookup by domain/email, and address standardization. A subset of calls can incur DaData charges; check
https://dadata.ru/mcp/ and your account's tariff. Requests send the supplied business identifiers or addresses
to DaData. The MCP output is reference data, not a guarantee of a counterparty's reliability.
