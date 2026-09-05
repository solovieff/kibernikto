---
name: kibernikto
description: Use when developing Kibernikto agents or Telegram bots.
version: 3.0.0
author: Kibernikto Team, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
compatibility: Use the existing repo environment; see pyproject.toml.
metadata:
  hermes:
    tags: [python, agents, telegram, pydantic-ai]
    related_skills: [building-pydantic-ai-agents, pydantic-ai-harness]
---

# Kibernikto Framework

Develop the local implementation, not a remembered PyPI API. Kibernikto combines
pydantic-ai agents, harness delegation, pluggable storage and an aiogram Telegram app.
This skill documents the working tree; recheck source before changing a contract.

## When to Use

- Editing `kibernikto/`, entry points, settings, tests or framework documentation.
- Building local experts or Telegram peer subagents, changing history, preprocessing,
  reply delivery, access control or Stars billing.
- Don't use for generic pydantic-ai or aiogram questions unrelated to this framework.

## Prerequisites

- Read the root `AGENTS.md` and `pyproject.toml` for project rules, Python requirements,
  dependencies and entry points. No IDE configuration is required to run code or tests.
- Use `read_file` / `search_files` for discovery and `patch` / `write_file` for edits.
  Run commands via `terminal` with the repository root as `workdir`.
- Use the existing virtual environment. **Do not install, sync dependencies, fetch,
  read live `.env` files, print credentials or start polling without authorization.**
- `pyproject.toml` declares Python >=3.11, pydantic-ai >=2.27.0,<3,
  aiogram >=3.30.0,<4 and pydantic-ai-harness >=0.18.0,<0.19.
  Project development conventions target Python 3.14+. Check the actual interpreter
  and locked dependencies; neither an old exact pin nor the metadata floor proves compatibility.

## How to Run

For an authorized live bot, with configuration ready before agent imports:

```python
terminal(command=".venv/bin/python main.py", workdir="<repo>")
```

`main.py` calls `start(outer_env=False)`. The CLI also accepts `--multi-agent` and
`--env_file_path`; see [Runtime](references/UTILS-AND-RUNNER.md) for the important
import-time dotenv limitation. On Windows use the existing venv's `Scripts/python.exe`.
Never start another poller for a token already owned by a running app.

## Procedure

1. Inspect the working tree and the affected implementation; preserve unrelated edits.
   Identify the actual exported class, settings reader and runtime caller.
2. Follow the request through `TelegramApp` → handlers → active `TelegramAgent` →
   `KiberniktoAgent.run` → storage. Verify which event observer and history namespace apply.
3. Make the smallest scoped change. Keep local experts as ordinary `KiberniktoAgent`
   instances; `KiberniktoExtended` is an optional orchestrator, not a requirement for experts.
4. Exercise offline tests with fake models/transports and isolated storage; verify docs
   imports and relative links. Report executed checks separately from live verification.

## Quick Reference

| Concern | Current contract |
|---|---|
| Base agent | `kibernikto.ai.agent.core.kibernikto_agent.KiberniktoAgent` |
| Telegram agent | `kibernikto.ai.agent.telegram.telegram_agent.TelegramAgent` |
| Active Telegram agent | `set_telegram_agent(agent)` in that same module; returns previous agent |
| App | `agent.to_telegram()` → `TelegramApp`; register agent separately before polling |
| Output | `AgentRunResult.output`, including structured output; not `result.data` |
| History | `history_storage=` injection; `chat_id=` enables load/save for async `run` |
| Storage | `APP_STORAGE_DATA_BACKEND=file|pg|sqlite`, `MEDIA_BACKEND=file|s3` |
| Local delegation | `SubAgents(agents=[SubAgent(agent), ...])` |
| Remote delegation | `TelegramPeerAgent` also works with real `SubAgent(peer)` |
| Ready peer builder | `build_subagents_agent_with_tg_peers(peers)` preserves local experts |

## References

- [Architecture](references/ARCHITECTURE.md): current files and request lifecycle.
- [Core agent](references/CORE-AGENT.md): imports, instructions, history and attachments.
- [Storage](references/STORAGE.md): file/SQL/S3 persistence and isolation.
- [Agents and harness](references/AGENTS-AND-HARNESS.md): experts, credit tiers, delegation.
- [Configuration](references/CONFIGURATION.md): real defaults and consumed env fields.
- [Telegram handlers](references/TELEGRAM-HANDLERS.md): registration and agent replacement.
- [Telegram peers](references/TELEGRAM-PEERS.md): registration, opt-in multimodal transport,
  input capture/selection, correlation, access and process-local limits.
- [Preprocessing](references/TELEGRAM-PREPROCESSING.md): media, quotes, transcription, PDF stub.
- [Middlewares](references/TELEGRAM-MIDDLEWARES.md): observer-specific order and permissions.
- [Payments](references/PAYMENTS.md): actual Stars transaction lookup and incomplete pieces.
- [Runtime and utilities](references/UTILS-AND-RUNNER.md): startup, logging, delivery and tests.
- [Common tasks](references/COMMON-TASKS.md): scoped implementation recipes.

## Pitfalls

- Recheck current source for API facts: `TelegramApp` owns polling, `TelegramAgent`
  lives in the AI agent package, and history defaults to the configured storage backend.
- The old `ServiceMiddleware` unconditional-forwarding debug expression is **not present**.
  Current forwarding skips admins. Do not reintroduce it or change service implementation
  merely to reconcile an old note.
- History request-boundary alignment and the fixed Stars period remain intentional.
- Telegram peer waits are process-local; SQL history does not make them durable jobs.
  Peer error policy is still under development: a passing happy path or generic error
  containment is not proof of complete recovery/retry semantics.

## Verification

Use [the offline runbook](references/UTILS-AND-RUNNER.md#offline-verification).
`scripts/check_docs.py` checks this entire skill's Markdown links, literal repo paths,
Python snippet syntax and import targets without loading secrets or using the network.
Verify the final diff contains only authorized files. No commit is implied by this skill.
