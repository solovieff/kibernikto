# Core Agent

Source: `kibernikto/ai/agent/core/kibernikto_agent.py`.

## Imports and construction

```python
from kibernikto.ai.agent import kibernikto_agent, KiberniktoDeps
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.base import MemoryHistoryStorage
from kibernikto.storage.singletons import history_storage, chat_data, media_store
```

`KiberniktoAgent` accepts normal pydantic-ai constructor kwargs plus
`history_storage=` (a `HistoryStorage` implementation or `None`). Global settings
are ordinarily env-derived; this does **not** prohibit agent dependency injection.

## History semantics

Only the overridden **async `run`** adds these semantics; do not assume inherited
`run_sync`, streaming or iteration APIs perform the same persistence.

- `chat_id=None`: no automatic history load/save or generated-image persistence.
- With a chat ID and non-None storage, load `get_conversation(chat_id)` unless
  `message_history` was explicitly supplied (even an empty list prevents loading).
- Append `run_result.new_messages()` on successful completion, including when the
  caller provided its own history. No automatic append occurs after a raised run error.
- `history_storage=None` disables history; a supplied chat ID still enables generated
  image archiving/publishing. Omit the chat ID for a fully storage-free text smoke test.
- The default is a factory-backed lazy proxy, **not** `MemoryHistoryStorage`.
  For isolated tests inject a new memory store; don't clear a production singleton's internals.

See [Storage](STORAGE.md) for namespaces, SQL startup and request-boundary windows.

## Instructions

Construction adds `resolve_instructions(self.name)` as pydantic-ai `instructions`.
It reads `{APP_STORAGE_FILESTORE_LOCATION}/{name}-instructions.txt` if present,
otherwise `AGENT_KIBERNIKTO_WHO_AM_I`. This still uses the filestore root with SQL data.
It resolves at construction, not on every request; later turns reuse those instructions.
Telegram adds dynamic bot identity and dependency-built conversation context.
Supplying `system_prompt` does not remove these base instructions.

## Model routing

`infer_kibernikto_model(None)` and an empty string return `None`. A nonempty model
without `:` raises `ValueError`; use a provider-prefixed string.

| Prefix | Implementation | Credential |
|---|---|---|
| `openrouter:` | `OpenRouterModel`, medium reasoning effort | `OPENROUTER_API_KEY` |
| `vsegpt:` | OpenAI-compatible endpoint at vsegpt | `VSEGPT_API_KEY` |
| `routerai:` | `RouterAiProvider` + OpenAI-compatible model | `ROUTERAI_API_KEY` |
| Other prefix | `pydantic_ai.models.infer_model` | provider-specific |

`PROVIDER_TYPE` is declared but does not route models. `APP_URL` and
`APP_INSTANCE_NAME` become OpenRouter app metadata. Provider availability is not
established by a model string being a source default.

## Attachments and output

Tools add `BinaryContent` using `deps.add_attachment` / `add_attachments`.
After the model returns, `_materialize_attachments` converts image binaries as needed
and adds `FilePart`s to the final response. The shared deps buffer remains intact so
parent runs can deliver binaries created by subagents. Images are archived through
`media_store`, published through `image_hosting`, and represented by URL text in
history; storage sanitization strips `FilePart`s. This is not a guarantee that all
non-image attachments are archived.

Read `result.output` for text **or structured output**; there is no supported
`result.data` split. Telegram's default renderer expects text. Customize `reply_to`
if using a structured output type.

## Adding tools and testing

A complete offline example (configuration must be isolated before imports):

```python
import asyncio
from pydantic_ai.models.test import TestModel
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.storage.base import MemoryHistoryStorage

async def smoke():
    history = MemoryHistoryStorage(history_size=6)
    agent = KiberniktoAgent(
        model=TestModel(custom_output_text="ok"), name="smoke",
        history_storage=history,
    )

    @agent.tool_plain
    def status() -> str:
        """Return the local test status."""
        return "ready"

    result = await agent.run("Hello", chat_id=42)
    assert result.output == "ok"
    assert await history.get_conversation(42)

asyncio.run(smoke())
```

The configured singleton also supports `@kibernikto_agent.tool` before use. For
new independent agents, explicitly decide their name, model, deps and history
namespace. See [offline verification](UTILS-AND-RUNNER.md#offline-verification).
