# Core Agent

`kibernikto.ai.agent` — a thin `pydantic_ai.Agent` subclass with per-chat history and multi-provider
model routing. **No Telegram dependency** — usable standalone in any async Python app.

## Class Hierarchy

```
pydantic_ai.Agent
    └── KiberniktoAgent          (kibernikto/ai/agent/core/kibernikto_agent.py)
            └── TelegramAgent    (kibernikto/telegram/agent/telegram_agent.py)
```

`KiberniktoAgent` adds only **one override**: `run(*args, chat_id=None, **kwargs)` that auto-loads
and saves per-chat history via `history_storage`. It also materialises tool-produced binary
attachments (`deps.attachments`) into the final `ModelResponse` as `FilePart`s.

`TelegramAgent` layered on top adds Telegram lifecycle: `process_message(message)` and
`reply_to(message, result)`. The default conversation handlers always delegate to the
`kibernikto_telegram_agent` singleton.

## Public Imports

```python
from kibernikto.ai.agent import kibernikto_agent          # configured singleton
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent  # base class
from kibernikto.ai.agent.core.history import history_storage            # shared storage
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS   # settings
from kibernikto.ai.agent.utils import infer_kibernikto_model            # model router
```

## `chat_id` Semantics

| `chat_id` | Behaviour |
|---|---|
| `None` | Plain `pydantic_ai.Agent.run` — no history loaded or saved |
| `int` | Loads `history_storage.get_conversation(chat_id)` before call; saves `run_result.new_messages()` after |

If the caller supplies `message_history=` in kwargs, the override does **not** overwrite it.

## Model Routing (`infer_kibernikto_model`)

`AGENT_KIBERNIKTO_MODEL_NAME` value determines the provider by its prefix before `:`:

| Prefix | Provider |
|---|---|
| `openrouter:` | `OpenRouterModel` with medium reasoning effort |
| `vsegpt:` | `OpenAIChatModel` via `https://api.vsegpt.ru:7090/v1` |
| `routerai:` | `OpenAIChatModel` via `https://routerai.ru/api/v1` |
| *(none)* | Falls through to `pydantic_ai.models.infer_model` (e.g. `openai:gpt-4.1`) |

> `AGENT_KIBERNIKTO_PROVIDER_TYPE` is declared in settings but **not** used for routing — the
> prefix in `MODEL_NAME` is what actually routes.

To add a new provider: write a `*_provider()` helper in `utils.py`, add an `elif` branch in
`infer_kibernikto_model`, and document the required env var.

## History Storage (`MemoryHistoryStorage`)

- **In-memory, process-local** — restart wipes everything.
- Window = last `AGENT_KIBERNIKTO_HISTORY_SIZE` (default 6) messages, walked back to the nearest
  `kind == 'request'` boundary. Window can be shorter than requested size by design.
- **Singleton** — both `kibernikto_agent` and any subclass instance share the same `history_storage`
  by default.
- To swap persistence (e.g. Redis): subclass `KiberniktoAgent` and override `run`, or monkey-patch
  `history_storage` before anything imports the agent module.

## Binary Attachments (`KiberniktoDeps`)

Tools cannot return binary content to the user directly (tool return goes back to the model). Instead
they append `BinaryContent` to `deps.attachments`. After `super().run()` returns,
`_materialize_attachments` folds those binaries into `run_result.response.parts` as `FilePart`s —
making them visible via `response.images` / `response.files` and serialisable into history.

`deps_type=KiberniktoDeps` is set on the singleton. Custom agents must also set it if they use tools
that produce attachments.

## Settings (`AgentKiberniktoSettings`, prefix `AGENT_KIBERNIKTO_`)

Key fields and their defaults:

| Env var | Default | Effect |
|---|---|---|
| `AGENT_KIBERNIKTO_MODEL_NAME` | `anthropic/claude-sonnet-4.6` | Routed by prefix |
| `AGENT_KIBERNIKTO_MODEL_MAX_TOKENS` | `760` | `ModelSettings.max_tokens` |
| `AGENT_KIBERNIKTO_MODEL_TEMPERATURE` | `0.7` | `ModelSettings.temperature` |
| `AGENT_KIBERNIKTO_MODEL_PARALLEL_TOOL_CALLS` | `true` | `ModelSettings.parallel_tool_calls` |
| `AGENT_KIBERNIKTO_HISTORY_SIZE` | `6` | `MemoryHistoryStorage` window |
| `AGENT_KIBERNIKTO_MODEL_MODALITIES` | `["text"]` | Add `"photo"` / `"audio"` for multimodal |
| `AGENT_KIBERNIKTO_WHO_AM_I` | *(Kibernikto persona)* | System prompt |

All other pydantic-ai constructor params (`output_type`, `toolsets`, `capabilities`, `retries`,
`mcp_servers`) are untouched — use the `building-pydantic-ai-agents` skill for those.

## Adding Tools

Attach directly to the singleton **before the first `.run()` call**:

```python
from pydantic_ai import RunContext
from kibernikto.ai.agent import kibernikto_agent

@kibernikto_agent.tool
async def get_weather(ctx: RunContext, city: str) -> str:
    """Return current weather for `city`."""
    ...
```

For a separate agent with the same model config, instantiate `KiberniktoAgent` with
`infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)` — both agents share `history_storage`
automatically.

## Testing

Standard pydantic-ai patterns apply — see `building-pydantic-ai-agents` skill for `TestModel` /
`FunctionModel`. History state is keyed by `chat_id`; clear `history_storage._storage[chat_id]` in
fixtures for isolation.

```python
from pydantic_ai.models.test import TestModel
from kibernikto.ai.agent import kibernikto_agent

async def test_agent():
    with kibernikto_agent.override(model=TestModel()):
        result = await kibernikto_agent.run("Hello!", chat_id=42)
        assert result.output
```
