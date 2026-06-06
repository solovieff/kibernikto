# Core Agent

The core layer is `kibernikto.ai.agent` — a thin wrapper around `pydantic_ai.Agent` with built-in
per-chat history management and multi-provider model inference. It has **no Telegram dependency**, so
you can use it as a standalone agent in any async Python app.

## Public Surface

```python
# The configured singleton — the one Telegram handlers call.
from kibernikto.ai.agent import kibernikto_agent
kibernikto_agent.run(user_message, chat_id=12345) -> AgentRunResult

# Underlying class (for subclassing or tests)
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent

# Process-local history (one per chat_id)
from kibernikto.ai.agent.core.history import history_storage, MemoryHistoryStorage

# Settings
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS

# Model inference
from kibernikto.ai.agent.utils import infer_kibernikto_model
```

## `KiberniktoAgent`

```python
# kibernikto/ai/agent/core/kibernikto_agent.py
from pydantic_ai import Agent, ModelSettings, AgentRunResult
from pydantic_ai.models import Model

from kibernikto.ai.agent.core.history import history_storage
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS


model: Model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)

model_settings: ModelSettings = ModelSettings(
    max_tokens=AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS,
    temperature=AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE,
    parallel_tool_calls=AGENT_KIBERNIKTO_SETTINGS.MODEL_PARALLEL_TOOL_CALLS,
)


class KiberniktoAgent(Agent):
    async def run(self, *args, chat_id: int | None = None, **kwargs) -> AgentRunResult:
        if chat_id is not None and 'message_history' not in kwargs:
            kwargs['message_history'] = history_storage.get_conversation(chat_id)

        run_result: AgentRunResult = await super().run(*args, **kwargs)

        if chat_id is not None:
            history_storage.add_messages(chat_id=chat_id, messages=run_result.new_messages())

        return run_result


agent = KiberniktoAgent(
    model=model,
    model_settings=model_settings,
    name=AGENT_KIBERNIKTO_SETTINGS.NAME,
    system_prompt=AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I,
)
```

The `run` override is the **only** custom behaviour. Everything else (tools, structured output,
streaming, capabilities, hooks, testing with `TestModel`/`FunctionModel`) is plain pydantic-ai — use
the `building-pydantic-ai-agents` skill for those topics.

### `chat_id` semantics

| `chat_id` | Behaviour |
|---|---|
| `None` | Behaves exactly like `pydantic_ai.Agent.run`. No history loaded, no history saved. |
| `int` | Loads `history_storage.get_conversation(chat_id)` into `message_history` before the call, then `history_storage.add_messages(chat_id, run_result.new_messages())` after. |

If the caller passes their own `message_history=...` in `kwargs`, the override does **not** clobber
it — it only fills the gap.

## Model Providers

`infer_kibernikto_model(model_name)` (in `kibernikto/ai/agent/utils.py`) dispatches on the prefix
before the first `:` in `model_name`:

| `AGENT_KIBERNIKTO_MODEL_NAME` value | Result |
|---|---|
| `openrouter:<provider/model>` | `OpenRouterModel(<model>, provider=openrouter_provider(), settings=OpenRouterModelSettings(openrouter_reasoning=OpenRouterReasoning(effort='medium')))` |
| `vsegpt:<model>` | `OpenAIChatModel(<model>, provider=OpenAIProvider(base_url='https://api.vsegpt.ru:7090/v1', api_key=VSEGPT_API_KEY))` |
| `routerai:<model>` | `OpenAIChatModel(<model>, provider=OpenAIProvider(base_url='https://routerai.ru/api/v1', api_key=ROUTER_AI_KEY))` (uses the same builder as vsegpt!) |
| Anything else (e.g. `openai:gpt-4.1`, `anthropic:claude-…`) | Falls through to `pydantic_ai.models.infer_model(model=...)` |

The three provider helpers in the same file:

```python
def vse_gpt_provider() -> OpenAIProvider:
    vsegpt_key = getenv('VSEGPT_API_KEY')
    assert vsegpt_key is not None, 'VSEGPT_API_KEY environment variable is not set.'
    return OpenAIProvider(base_url='https://api.vsegpt.ru:7090/v1', api_key=vsegpt_key)


def routerai_provider() -> OpenAIProvider:
    routerai_key = getenv('ROUTER_AI_KEY')
    assert routerai_key is not None, 'ROUTER_AI_KEY environment variable is not set.'
    return OpenAIProvider(base_url='https://routerai.ru/api/v1', api_key=routerai_key)


def openrouter_provider() -> OpenRouterProvider:
    return OpenRouterProvider(app_url=APP_SETTINGS.URL, app_title=APP_SETTINGS.INSTANCE_NAME)
```

### Add a new provider

1. Write a `*_provider() -> Provider` helper in `kibernikto/ai/agent/utils.py`.
2. Extend `infer_kibernikto_model` with a new `elif provider_name == '<name>':` branch.
3. Bump `Literal[...]` in `AgentKiberniktoSettings.PROVIDER_TYPE` (`kibernikto/ai/agent/core/config.py`) — though this `Literal` is declared but **not** read by `infer_kibernikto_model` today (the prefix on `MODEL_NAME` is what actually routes).
4. Document the new env var (e.g. `MYPROV_API_KEY`) next to the helper.

## History Storage

```python
# kibernikto/ai/agent/core/history.py
from collections import defaultdict
from typing import List, Dict
from pydantic_ai.messages import ModelMessage
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS


class MemoryHistoryStorage:
    def __init__(self, history_size: int = AGENT_KIBERNIKTO_SETTINGS.HISTORY_SIZE):
        self._storage: Dict[int, List[ModelMessage]] = defaultdict(list)
        self._history_size = history_size

    def get_conversation(self, chat_id: int) -> List[ModelMessage]:
        messages: List[ModelMessage] = self._storage[chat_id]
        if not messages:
            return []
        start_index = max(0, len(messages) - self._history_size)
        # Walk back until we hit a user "request" message
        while start_index > 0 and messages[start_index].kind != 'request':
            start_index -= 1
        # If the start is still not a request, scan forward
        while start_index < len(messages) and messages[start_index].kind != 'request':
            start_index += 1
        return messages[start_index:]

    def add_messages(self, chat_id: int, messages: List[ModelMessage]):
        self._storage[chat_id].extend(messages)


history_storage = MemoryHistoryStorage()
```

### Key properties

- **In-memory, process-local** — restart wipes everything. No Redis/DB is wired in.
- **`HISTORY_SIZE` defaults to 6** — set `AGENT_KIBERNIKTO_HISTORY_SIZE` to change.
- **Aligned to a user turn** — the start of the returned history is always a `kind == 'request'`
  message. This means the window can be **shorter** than `HISTORY_SIZE` if the natural cut-off is in
  the middle of a request/response pair.
- **Singleton** — `history_storage` is module-level. Two `KiberniktoAgent` instances share the same
  history by default.

### Replace the storage

To persist history (e.g. Redis), substitute the singleton before importing anything that touches
`kibernikto_agent`:

```python
# my_app/main.py
from kibernikto.ai.agent.core.history import MemoryHistoryStorage
import kibernikto.ai.agent.core.history as _h
import kibernikto.ai.agent.core.kibernikto_agent as _a

_h.history_storage = MyRedisHistoryStorage()
_a.history_storage = _h.history_storage  # the subclass reads it from the module
```

Or, more cleanly, subclass `KiberniktoAgent` and override `run` to call your own backend.

## AgentKiberniktoSettings

```python
# kibernikto/ai/agent/core/config.py
import logging
from typing import Literal, List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = "Respond to all my questions as Kibernikto. Kibernikto is a gentle universe creator. He isn't afraid to joke in a sinister manner. Kibernikto never tries to avoid a specific answer including concrete names and events."


class AgentKiberniktoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='AGENT_KIBERNIKTO_')

    NAME: str = Field(default="kibernikto", description="Default kibernikto agent")

    PROVIDER_TYPE: Literal["openai", "gateway", "openrouter", "vsegpt", "custom_openai"] = Field(
        default="openrouter", description="API provider type"
    )
    HISTORY_SIZE: int = Field(default=6, description="History size")
    MODEL_NAME: str = Field(default="anthropic/claude-sonnet-4.6", description="Model name")
    MODEL_MAX_TOKENS: int = Field(default=760, description="Model max tokens")
    MODEL_TEMPERATURE: float = Field(default=0.7, description="Model temperature")
    MODEL_PARALLEL_TOOL_CALLS: bool = Field(default=True, description="Parallel tool calls")
    MODEL_MODALITIES: List[Literal['text', 'photo', 'audio']] = Field(
        default=['text'], description="Photo or audio modalities"
    )

    WHO_AM_I: str = Field(default=DEFAULT_SYSTEM_PROMPT, description="Who am I")


AGENT_KIBERNIKTO_SETTINGS = AgentKiberniktoSettings()


def print_banner():
    logger = logging.getLogger('kibernikto')
    logger.info(AGENT_KIBERNIKTO_SETTINGS.model_dump_json(indent=2))
```

### Defaults

| Field | Default | Notes |
|---|---|---|
| `NAME` | `"kibernikto"` | Used as the agent's `name=` (pydantic-ai attribute) |
| `PROVIDER_TYPE` | `"openrouter"` | Currently informational — the prefix in `MODEL_NAME` is what routes |
| `HISTORY_SIZE` | `6` | Window size for `MemoryHistoryStorage` |
| `MODEL_NAME` | `"anthropic/claude-sonnet-4.6"` | Routed as `openrouter:anthropic/claude-sonnet-4.6` once you set `AGENT_KIBERNIKTO_MODEL_NAME=openrouter:...` |
| `MODEL_MAX_TOKENS` | `760` | Applied to `ModelSettings.max_tokens` |
| `MODEL_TEMPERATURE` | `0.7` | Applied to `ModelSettings.temperature` |
| `MODEL_PARALLEL_TOOL_CALLS` | `True` | Applied to `ModelSettings.parallel_tool_calls` |
| `MODEL_MODALITIES` | `['text']` | Set to `['text', 'photo']` to opt into image understanding, `['text', 'audio']` for native audio |
| `WHO_AM_I` | `DEFAULT_SYSTEM_PROMPT` | The system prompt |

### Defaults from `pydantic-ai` that survive the override

The `KiberniktoAgent` constructor only sets `model`, `model_settings`, `name`, and `system_prompt`.
Everything else (`output_type`, `deps_type`, `toolsets`, `capabilities`, `retries`, `instrument`,
`mcp_servers`) defaults to `pydantic-ai`'s defaults. See the `building-pydantic-ai-agents` skill for
how to add structured output, tools, capabilities, and hooks.

## Adding Tools

Tools are pure pydantic-ai — use `@kibernikto_agent.tool` or `@kibernikto_agent.tool_plain`. Add them
**after** import and before the first `.run()` call, typically in your own module that imports
`kibernikto_agent`:

```python
# my_tools.py
from pydantic_ai import RunContext
from kibernikto.ai.agent import kibernikto_agent


@kibernikto_agent.tool
async def get_weather(ctx: RunContext, city: str) -> str:
    """Return current weather for `city`."""
    # ... call your weather API ...
    return f"It is sunny in {city}."
```

If you need a **separate** agent with the same configuration but a different tool set, subclass:

```python
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.utils import infer_kibernikto_model

base_model = infer_kibernikto_model(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME)

search_agent = KiberniktoAgent(
    model=base_model,
    system_prompt="You are a search-focused Kibernikto.",
)


@search_agent.tool
async def web_search(ctx, query: str) -> str:
    """Search the web and return a summary."""
    ...
```

To **share** the same `chat_id` history with `kibernikto_agent`, reuse the module-level
`history_storage` — both agents use the same singleton by default.

## Testing

The core agent is a `pydantic_ai.Agent`, so the standard pydantic-ai testing patterns work:

```python
from pydantic_ai.models.test import TestModel
from kibernikto.ai.agent import kibernikto_agent


async def test_kibernikto_agent():
    with kibernikto_agent.override(model=TestModel()):
        result = await kibernikto_agent.run("Hello!", chat_id=42)
        assert "success" in result.output
```

For deterministic conversation state, the `chat_id` argument is enough — `MemoryHistoryStorage` is
reset between tests if you create a fresh `KiberniktoAgent` with a fresh storage, or you can pop the
relevant key from `history_storage._storage` in `pytest` fixtures.

See the `building-pydantic-ai-agents` skill for `TestModel`, `FunctionModel`, and Logfire-based
debugging patterns.
