# Agents and harness

Sources: `kibernikto/ai/agent/extended/orchestrators.py`,
`kibernikto/ai/agent/extended/kibernikto_extended.py`, `kibernikto/ai/agent/harness/`.

## Local agents and orchestrator

Keep experts as normal `KiberniktoAgent` instances with a name, description, model,
tools and compatible deps. `KiberniktoExtended` is useful for a Telegram parent with
credit-based model selection; it is not required to register or call an expert.

```python
from pydantic_ai_harness.subagents import SubAgent, SubAgents
from kibernikto.ai.agent.harness.conversation_agent import conversation_agent

capability = SubAgents(
    agents=[SubAgent(conversation_agent)], agent_folders=None, contain_errors=True,
)
```

Attach the capability through a parent's `capabilities=`. The harness supplies
`delegate_task`; do not replace this with ad-hoc string dispatch or assume that
all imported expert modules are enabled.

`build_subagents_agent()` currently registers **web, image and conversation**.
Report and scheduler modules are imported but are not in `_EXPERT_AGENTS`.
The parent also gets `WebSearch()`. The `--multi-agent` CLI flag selects the
prebuilt `kibernikto_subagents_agent` with these locals only; peer IDs in env do
not automatically add remote subagents.

`build_subagents_agent_with_tg_peers(peers)` creates the same kind of parent,
preserves local experts, then adds each peer as
`SubAgent(peer)` without an outer harness timeout: the peer owns its deadline,
avoiding a cancellation race with a second equal timeout. See [Telegram peers](TELEGRAM-PEERS.md).
Error containment is configured, but do not equate `contain_errors=True` with a
finished peer failure taxonomy, safe retry policy or live parent recovery proof.

## Extended agent and context

`KiberniktoExtended` injects `get_history_storage(agent_name)` unless overridden.
For a supplied chat ID it loads shared `ConversationInfo`, selects a model by
credit tier unless a run model was explicitly supplied, and after success charges
one credit and saves. Balances never go below zero; low balance selects a cheaper
model rather than denying access. This is not Telegram Stars billing.

The base instructions come from a named instruction file or `WHO_AM_I`; the
extended class's older Kalki/JSON-only docstrings are not a separate hard-coded
persona/backend. Telegram instructions add bot identity and conversation context.
`TelegramDeps` carries chat/user/message/timezone fields plus inherited attachments,
input parts and context. Several tools access `deps.chat_id`, which the base
`KiberniktoDeps` alone does not provide: supply Telegram deps or another compatible
context rather than assuming a bare base deps object satisfies every expert.

## Expert inventory

| Expert source | Tools / behavior | Limits |
|---|---|---|
| `kibernikto/ai/agent/harness/web_agent/web_expert.py` | `read_web`, `web_search`, `deep_search` via Jina | real network calls; read/search responses truncated to 8000 chars |
| `kibernikto/ai/agent/harness/image_agent/image_expert.py` | `describe_image`, `edit_image` | vision model is separately hard-coded; editing calls core generation with deps input images |
| `kibernikto/ai/agent/harness/conversation_agent/conversation_expert.py` | `add_user_info`, `set_user_info`, `answer_on_full_history` | full-history tool formats default namespace history (up to 5000), not necessarily the named parent's history |
| `kibernikto/ai/agent/harness/report_agent/report_expert.py` | `generate_report`, Jina with VseGPT fallback | attaches text bytes; imported report singleton needs VseGPT config even though disabled in default delegation |
| `kibernikto/ai/agent/harness/scheduler_agent/scheduler_expert.py` | plan/replan/delete/clear events, set timezone | separate JSON store; **no notification execution daemon**, not wired by default |

Core image generation lives in `kibernikto/ai/agent/core/image.py`. Telegram registers
its tool only when `IMAGE_MODEL_NAME` is truthy; the image expert's edit tool also
calls it. Do not promise a generation tool merely because an image expert exists.

## Verification

Importing orchestrators constructs expert singletons, including disabled experts.
For offline checks mock model inference or provide explicit fake provider settings
before imports. Never load a live env file to satisfy an import test.
Run the peer builder tests and verify the real installed harness contract (not a
hand-built fake `SubAgent`). Keep remote calls bounded and distinguish process-local
async waits from pydantic-ai durable deferred execution. No durable deferred peer
resume is implemented here.
