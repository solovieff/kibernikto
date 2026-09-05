# Telegram peer sub-agents

`TelegramPeerAgent` is a `KiberniktoAgent`. Use the opt-in public builder;
the original `build_subagents_agent()` and its singleton are unchanged:

```python
from dotenv import load_dotenv
load_dotenv('caller.env')  # Before importing configuration-dependent agents.

from kibernikto.ai.agent.extended.orchestrators import build_subagents_agent_with_tg_peers
from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
from kibernikto.ai.agent.telegram.telegram_agent import set_telegram_agent

poet = TelegramPeerAgent(peer='@YourPoetBot', name='poet',
                         description='Пишет стихи по заданной теме, размеру и настроению.')
agent = build_subagents_agent_with_tg_peers([poet])
set_telegram_agent(agent)
agent.to_telegram().run_polling()
```

For startup validation and SQLite parent-directory creation, prefer the runnable
[example](../examples/telegram_peers.py):

```sh
python -m examples.telegram_peers --env-file worker.env \
  --instructions 'Ты поэт. Пиши стихи по теме, размеру и настроению из запроса.'
python -m examples.telegram_peers --env-file caller.env --peer @YourPoetBot
```

Each process uses its own token and storage path. No peer token belongs in the
caller config. The worker's actual instructions configure its behavior; the
peer description only tells the caller when to delegate. Nothing is sent on startup.

Alternatively, register it exactly like an existing expert in
`kibernikto/ai/agent/extended/orchestrators.py`:

```python
from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent

swarm = TelegramPeerAgent(
    peer='@swarm_host_bot',  # Or a positive numeric private-chat ID.
    name='swarm',
    description='Пишет стихи по заданной теме, размеру и настроению.',
    timeout=60,
)
_EXPERT_AGENTS = [web_agent, image_agent, conversation_agent, swarm]
# Existing SubAgents(agents=[SubAgent(agent) for agent in _EXPERT_AGENTS]) stays unchanged.
```

The caller needs **its own** bot token, not the remote bot's token. A peer's
Telegram address explicitly selects remote execution. Local experts remain local.
`KiberniktoExtended` (credits/model balancing) is not required for every expert.

## Request path

1. `SubAgents.delegate_task` calls `peer.run(task, deps=ctx.deps, ...)`.
2. The peer uses the caller's `TelegramDeps.message.bot` and the active app's hub.
3. An internal Telegram model adapter sends the task as plain text by default,
   or as an atomic document envelope with explicitly selected bytes when
   `multimodal=True`. No local LLM is called and no caller tools or credentials
   are sent to the peer.
4. The existing aiogram Dispatcher receives the reply. `PeerMiddleware` runs
   before service forwarding, firewall, subscriptions and conversation handlers.
5. Only a private reply from the exact peer to the exact outbound message resolves
   the wait. Unrelated messages continue through the ordinary pipeline.
6. PydanticAI produces a real `AgentRunResult`, including request/response history,
   rather than a fabricated result object with missing graph state.

The coroutine waits asynchronously; the event loop remains available. Do not use
sequential update processing or a concurrency limit that leaves no slot for the
reply update while an originating request waits. There is **one poller per bot**.

Outside a Telegram handler, supply `bot=app.bot, hub=app.peer_hub` explicitly and
keep that app's Dispatcher running. Never start a second `getUpdates` consumer
for an already-running bot.

## Receiving requests on Kibernikto

Enable Bot-to-Bot Communication Mode in BotFather for both bots. On the receiving
Kibernikto process, explicitly opt in caller IDs:

```dotenv
TG_PEER_IDS=[7731368093]
```

Normal firewall permissions still apply to **new requests**: with `TG_PUBLIC=false`,
include the caller in `TG_MASTER_IDS` as appropriate. `TG_PEER_IDS` alone does not
grant general access. Expected answers to our own requests are instead admitted
by exact correlation, without granting the peer permission to start conversations.

Only private, non-reply messages from opted-in bots may start an agent run.
Answers are anchored Telegram replies. Unmatched bot replies never start another
LLM run. Existing human conversations and group behavior remain unchanged.

A third-party bot or a person need not run Kibernikto for **default text mode**,
but must be reachable under Telegram's rules and reply to the particular request.
Humans must first allow a bot conversation; a bot cannot contact arbitrary users
by username. Multimodal mode requires the versioned Kibernikto envelope protocol;
an ordinary text reply or a standalone photo/file does not complete that call.

## Opt-in multimodal transport

```python
from kibernikto.ai.agent.extended.orchestrators import build_subagents_agent_with_tg_peers
from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent

vision = TelegramPeerAgent(
    peer='@YourVisionBot',
    name='vision',
    description='Describes the selected image and returns a report.',
    multimodal=True,
)
agent = build_subagents_agent_with_tg_peers([vision])
agent.capture_peer_media = True  # Opt in before processing Telegram updates.
```

`multimodal` defaults to `False`. Registration and `SubAgents.delegate_task` stay
the same; the task is still a non-empty string and `result.output` is text.
Returned binary files are available through `result.response.files`.

### Select only the inputs intended for this peer

On the run's `KiberniktoDeps` / `TelegramDeps`:

- `deps.peer_inputs = [selected_binary, ...]` explicitly selects `BinaryContent`
  objects to send. MIME types and optional `vendor_metadata['filename']` travel
  with the inline bytes.
- `deps.peer_inputs = []` sends no binaries, even if the current request has media.
- `deps.peer_inputs = None` (the default) selects only `BinaryContent` already in
  `deps.user_message_parts`, not URLs or other content types.

Set this selection in application/tool code before delegation. The peer does not
forward the whole dependency container, caller history, system instructions,
previous output attachments, or files from disk. Only the delegated task string
and selected bytes cross the transport. Selection is run-scoped; applications
delegating different inputs concurrently should use separate dependency copies.

For normal Telegram updates, `TelegramAgent(..., capture_peer_media=True)` opts
into **current-message** capture. The public builder's returned agent also exposes
the `capture_peer_media` attribute, as above. Capture downloads the largest photo
variant, voice, audio, or document from the current update and places the bytes in
`deps.peer_inputs`. It does not walk `reply_to_message`, history, or local storage,
and does not assemble albums. The lower-level helper is
`await capture_peer_inputs(message)` from `kibernikto.telegram.peer_inputs`;
custom callers must enforce access checks before invoking it.

Capture mode bypasses the legacy preprocessor: the model receives current
text/caption (or a fallback prompt) plus images. Audio and document bytes remain
available in `deps.peer_inputs` for explicit tools/delegation. Receiving a peer
envelope likewise supplies its images to the model and all its binaries to
`deps.peer_inputs`, without loading the receiving chat's history for that run.

**Transport is not interpretation.** Photos, audio/voice, PDFs and other documents
can travel as bytes, but this does not implement PDF/document parsing, OCR, audio
transcription, or model support for every media type. Document parsing is postponed.
The default preprocessor's existing audio behavior is not used by capture mode;
configure explicit interpretation tools if the worker needs them. With capture
disabled, existing preprocessing remains unchanged.

### Atomic wire format and limits

Multimodal requests and responses use one `sendDocument` each, with filename
`kibernikto-peer-v1.json`, JSON MIME type and caption
`KIBERNIKTO_PEER/1 <kind> <request_id>`. Version 1 defines `request`, `result` and
`error` envelopes. The JSON contains `version`, `kind`, `request_id`, `text`,
`parts`, and `end: true`; each part carries inline base64 `data`, `media_type`
and an optional filename value. Responses must be Telegram replies to the exact
outbound document and carry the same request ID.

Limits in `kibernikto/telegram/peer_protocol.py` apply to each whole envelope:

| Constant | Limit |
| --- | --- |
| `MAX_WIRE_BYTES` | 3 MiB of encoded JSON |
| `MAX_BINARY_BYTES` | 2 MiB of decoded binary data in total |
| `MAX_PARTS` | 8 binary parts |
| `MAX_TEXT` | 65,536 text characters |

The public `peer.run()` currently also limits its task prompt to 4,096 UTF-16
units in both modes; the envelope text limit is not a promise of longer task
prompts. MIME labels are validated and limited to 127 characters; optional
filenames are limited to 128 characters and must not contain path separators,
control characters, or the names `.` / `..`. Unknown fields, duplicate JSON keys,
unsupported versions and incomplete envelopes are rejected. Both metadata and
streamed download size are bounded.

There is no URL/path attachment-fetching protocol: parts contain bytes, not
remote URLs, caller-local paths or reusable Telegram file IDs. Filenames are
metadata, not instructions to open or write a path. Downloads use only the
receiving bot's Telegram `getFile` result. In the normal Dispatcher path, new bot
requests pass the firewall and `TG_PEER_IDS` checks **before envelope download**;
response downloads require exact bot/chat/sender/message/request correlation,
not an additional inbound whitelist entry.

A complete validated result delivers its text and binaries together. Progress
text, standalone media, edits and unrelated documents do not complete an envelope
call. Remote binaries are appended once to the caller's `deps.attachments`,
preserving existing attachments, and are materialized in the response for normal
Telegram delivery. This is atomic result handling, not durable exactly-once
execution across process restarts.

## Deliberate limits

- Private requests only: numeric IDs or resolvable `@username` addresses, not
  groups/channels. Default text requests must fit one Telegram message.
- Requires an explicit Telegram reply. No guessing by 'latest message from peer'.
- In **default text mode**, the first text/caption reply completes a call. Chunked
  answers, streamed edits and binary attachments are not assembled. Use a
  protocol-compatible peer with `multimodal=True` for atomic text-plus-bytes results.
- Pending waits are in memory, bounded by timeout and cancelled on shutdown.
  Restart recovery is **not** implemented. Do not mistake saved dialogue history
  for durable outstanding calls.
- Remote LLM usage/cost is not reported by Telegram; local usage accounting only
  sees a transport request, not the remote model's real token consumption.
- Inherited streaming/iteration entry points are not part of the peer API; use
  `.run()` as `SubAgents` does.

For durable pauses the relevant PydanticAI primitive is **external deferred tool
execution** (`CallDeferred`, `DeferredToolRequests.calls`, `DeferredToolResults.calls`),
not tool approval. It additionally needs persisted call correlation, parent run
state, deduplication and resume orchestration. Neither mode implements that feature.

## Failure policy

Direct `await peer.run(...)` raises `PeerError` on expected transport failures.
Through the supported `SubAgents` path, PydanticAI records a native
`ToolReturnPart(outcome='failed')` containing a `telegram_peer_failure` JSON
observation; it is not a remote answer and does not consume model retry budget.

- Rejected requests (400/403): `category=rejected`, `delivery=not_sent`.
- Telegram rate limit: `category=rate_limited`, includes `retry_after`; no automatic sleep/resend.
- Network interruption: `category=network`; delivery may be `unknown` if sending began.
- Peer deadline: `category=timeout`; includes the configured timeout.
- Username resolution failure: delivery is `not_sent` because no task was submitted.
- Invalid or oversized multimodal envelopes: `category=protocol`; no automatic resend.
- A correlated multimodal `error` envelope: `category=remote`, not a successful
  answer. Kibernikto workers send generic error text for caught execution failures,
  rather than internal exception details.
- Cancellation and shutdown propagate cancellation, not a fabricated failure response.

No automatic resend is performed. The model can explicitly decide a next action;
a new explicit tool call is a new request, not a promise of exactly-once delivery.
A remote model may continue running after the local deadline. If sending the remote
answer fails, the caller sees a timeout, not the remote exception itself.

The builder leaves `SubAgent.timeout_seconds` unset: the peer owns its deadline.
Adding an equal/shorter outer harness timeout can replace the native failed outcome
with the harness's generic timeout observation. Do not stack equivalent timers.
The compatibility path is regression-tested against the declared dependency versions;
keep these tests when upgrading pydantic-ai or its harness.

## Offline tests

```sh
.venv/bin/python -B .agents/skills/kibernikto/scripts/check_docs.py --tests
```

Tests use actual PydanticAI `SubAgents` and aiogram Dispatcher, with deterministic
models and mocked Telegram HTTP only. They do not load production `.env` or spend
LLM credits.
