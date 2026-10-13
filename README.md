# kibernikto

Kibernikto is a multi-agent AI framework with a Telegram bot connection, built on
[pydantic-ai](https://ai.pydantic.dev) and aiogram 3. Run it as a ready Telegram bot or use
`KiberniktoAgent` as the core of your own multi-agent app.

> **2.0 is in beta** and is a full rewrite: 1.x code and env names are not compatible.
> See the [changelog and migration table](CHANGELOG.md).

**Telegram**

- ✍️ conversations with AIs in groups or privately, per-chat history
- 🔉 voice message transcription
- 📸 image understanding and generation
- 🤖 other Telegram bots as delegated sub-agents ([peers](docs/telegram-peers.md))
- ⭐️ Telegram Stars subscriptions
- 🧐 user messages and errors forwarded to a service group

**Core**

- 🐫 `KiberniktoAgent` — a `pydantic_ai.Agent` with injectable per-chat history
- 🧩 local experts (web, image, conversation) via pydantic-ai-harness `SubAgents`
- 💾 history in files, SQLite or PostgreSQL; media in files or S3; public images via imgbb or S3
- 🔭 Logfire tracing of every agent, model and tool call

## Install

```shell
pip install --pre kibernikto   # 2.0 beta
```

## Run the Telegram bot

1. Copy [`deploy/tg_bots/kibernikto/kibernikto.env`](deploy/tg_bots/kibernikto/kibernikto.env) and fill in at least
   `TG_BOT_KEY`, `TG_MASTER_ID` and the provider key for your model (e.g. `OPENROUTER_API_KEY`).
2. Start it — **one process per bot token**:

```shell
kibernikto --env_file_path=/path/to/kibernikto.env               # single agent
kibernikto --env_file_path=/path/to/kibernikto.env --multi-agent # with local experts
```

Models are provider-prefixed: `openrouter:vendor/model`, OpenAI-compatible gateways
(`vsegpt:`, `routerai:`, `beget:` — key in `VSEGPT_API_KEY`, `ROUTERAI_API_KEY`, `BEGET_AI_API_KEY`)
or any [pydantic-ai model string](https://ai.pydantic.dev/models/overview/). A new gateway is one
`OPENAI_COMPATIBLE_PROVIDERS` entry in `kibernikto/ai/agent/utils.py`.

## Deploy

Both Dockerfiles default to `--multi-agent`. In this mode,
`AGENT_KIBERNIKTO_ALLOW_ZERO_CREDITS=true` (default) keeps chats on the poor model
when credits run out; `false` blocks billable agent runs at balance ≤ 0 with a `/pay` hint.
Charging stops at zero. Non-billable peer envelopes are exempt; subscription checks are independent.

[`deploy/`](deploy/README.md) is a ready server layout: copy it, add a deploy key and env, run as root:

```shell
deploy/scripts/rebuild.sh -b kibernikto   # clone from git, build, run as kibernikto.service (podman + systemd)
deploy/scripts/update.sh                  # rebuild every bot with new commits
```

One folder per bot in `deploy/tg_bots/`. Plain Docker, storage, backups and rollback:
[deployment runbook](docs/deployment.md).

## Telegram peer agents

Add a Telegram bot alongside local experts with
`build_subagents_agent_with_tg_peers([TelegramPeerAgent(...)])`.

- [Peer API, access rules and limitations](docs/telegram-peers.md)
- [Runnable caller + poetry-worker example](examples/telegram_peers.py)

## Development

Python 3.14 and the locked dependencies in `uv.lock`:

```shell
uv sync
uv run python -m unittest discover -s tests -q
uv run python main.py --env_file_path=env/kibernikto.env
```