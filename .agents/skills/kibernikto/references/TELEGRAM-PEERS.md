# Telegram peer subagents

Sources: `kibernikto/ai/agent/telegram/peer_agent.py`,
`kibernikto/telegram/peer_hub.py`, `kibernikto/telegram/peer_protocol.py`,
`kibernikto/telegram/peer_inputs.py`, `kibernikto/ai/agent/telegram/telegram_agent.py`,
`kibernikto/telegram/middleware/middleware_peer.py`,
`kibernikto/ai/agent/extended/orchestrators.py`.

## Register a real subagent

`TelegramPeerAgent` is a `KiberniktoAgent` using an internal Telegram-backed
pydantic-ai model. It returns a real `AgentRunResult[str]`; no separate local LLM
performs the remote inference. It is accepted by the actual harness `SubAgent(peer)`.
A remote bot token is **not** needed on the caller. Text transport remains the
compatible default; `multimodal=True` opts into the version-1 document protocol.

```python
from pydantic_ai_harness.subagents import SubAgent, SubAgents
from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
from kibernikto.ai.agent.extended.orchestrators import build_subagents_agent_with_tg_peers
from kibernikto.ai.agent.telegram.telegram_agent import set_telegram_agent

peer = TelegramPeerAgent(
    peer="@example_poet_bot", name="poet",
    description="Пишет стихи по заданной теме, размеру и настроению.",
    timeout=60, multimodal=True,
)

# Normal harness registration works alongside any local experts:
capability = SubAgents(
    agents=[SubAgent(peer)],
    agent_folders=None, contain_errors=True,
)

# Or preserve the project's existing local experts using the builder:
agent = build_subagents_agent_with_tg_peers([peer])
# Optional: preserve current incoming Telegram media for later delegation.
agent.capture_peer_media = True
set_telegram_agent(agent)
app = agent.to_telegram()
# Authorized live execution only: app.run_polling()
```

Construction does not send Telegram requests or poll. Configured model imports can
still require provider keys, including the imported but disabled report expert;
use the offline verifier for construction checks rather than live credentials.

`peer` accepts a positive private user/chat ID or an `@username` matching the source
validator. `name` and `description` identify the harness expert; timeout must be
finite and positive. The builder uses `SubAgent(peer)` without a `timeout_seconds`
wrapper: the peer owns its timeout, avoiding an outer deadline cancellation race.
Do not normalize an invalid ID/username silently. Numeric route validation also
rejects self-routing and IDs outside the supported range. The local description
advertises the poet to the caller; configure the remote bot's poetry instructions
separately.

The runnable example `examples/telegram_peers.py` offers worker mode (no `--peer`)
and caller mode (`--peer`), with required `--env-file` loaded before framework
imports. `--peer-description` advertises the expert to the caller; `--instructions`
configures the running bot, not the remote peer. It registers the selected agent,
prepares file-SQLite parent directories and starts polling without sending a sample
delegation automatically. Use it only for an authorized live launch; do not assume
its CLI enables multimodal transport without checking its current flags.

## Input selection and capture

`multimodal=True` changes the peer wire transport, not the parent model or normal
Telegram preprocessing. It still takes a nonempty string `user_prompt`; pass
attachments through `KiberniktoDeps` / `TelegramDeps`, not a list-valued prompt.
Selection is explicit and run-scoped:

- `deps.peer_inputs is None`: select only `BinaryContent` in the current
  `deps.user_message_parts`.
- `deps.peer_inputs == []`: deliberately send no attachments, even when current
  message parts contain binaries.
- A nonempty `deps.peer_inputs`: send exactly that list, in order.
- Without compatible deps, send no attachments. History, URLs, local paths and
  `deps.attachments` are not implicitly selected; attachments is the output queue.

`TelegramAgent(capture_peer_media=True, ...)` is an independent, opt-in input flag
(default `False`). The builder returns a Telegram agent, so the example sets the
same flag on that instance before polling; the builder has no capture argument.
For ordinary incoming messages, capture bypasses the normal preprocessor. It
preserves current-message photo (largest Telegram size), voice, audio and document
bytes via `capture_peer_inputs`, then populates `deps.peer_inputs`. It does not
capture quoted/history media or assemble albums. The model prompt contains the
message text/caption (or a fallback instruction) and images only; audio/documents
remain available to tools and delegation through deps. Capture does not transcribe
audio or parse documents. Parsing PDF/Office documents is outside this transport.

Safe audio/document filenames and their declared MIME types are retained. Missing
MIME types use `application/octet-stream`; missing/unsafe names use `audio.bin` or
`document.bin`. Photos use `image/jpeg` / `photo.jpg`, voices `audio/ogg` / `voice.ogg`.
These are Telegram-provided bytes, not a promise to recover an original photo before
Telegram compression. Size metadata and bounded download buffers enforce the
aggregate input limit; failures do not return a partial selection.

An authorized inbound protocol request is decoded independently of the capture
flag: all its binaries populate `deps.peer_inputs`, while text and image binaries
form the model prompt. Its run uses `chat_id=None`, avoiding automatic per-chat
history for that request. Non-image content is carried, not automatically understood
by the remote model. Tools may select/redelegate it or implement their own processing.

## Atomic version-1 document protocol

With `multimodal=True`, both ends must support the same protocol. Each request,
result or error is **one Telegram document**, not a caption plus separately sent
media or a media group. There is no multipart assembly or negotiation/fallback to
text. The document filename is `kibernikto-peer-v1.json`, MIME `application/json`,
with caption `KIBERNIKTO_PEER/1 <kind> <request_id>` and no parse mode.

The UTF-8 JSON object has exactly `version`, `kind`, `request_id`, `text`, `parts`
and `end`: `version` is integer `1`; kind is `request`, `result` or `error`;
request ID is 32 lowercase hexadecimal characters; `end` must be `true`. Each part
has exactly `data` (strict inline base64), `media_type` and `filename` (string or
null). The caption must match the decoded kind and request ID. Unknown fields,
duplicate keys, unsupported versions, incomplete envelopes and invalid parts fail
validation. No URL/path fetching is encoded in the envelope.

The envelope preserves each binary's bytes, MIME type and optional filename from
`BinaryContent.vendor_metadata['filename']`, in order. Other vendor metadata is
not serialized. Wire filenames must be safe basenames: nonempty, at most 128
characters, no slash/backslash or control characters, and not `.` or `..`.
MIME types must match the protocol's type/subtype token validator and be at most
127 characters; invalid metadata is rejected, not silently repaired by the codec.

Current application limits (not Telegram's general upload limits):

| Item | Limit |
|---|---|
| Encoded document, including JSON/base64 | 3 MiB |
| Aggregate decoded binary data | 2 MiB |
| Binary parts per envelope | 8 |
| Envelope text | 65,536 characters |
| Public peer `run` prompt | 4,096 UTF-16 units, nonblank, including multimodal mode |

The public adapter's prompt guard is currently stricter than the codec's text
limit. Sending validates before upload; receiving checks document/getFile metadata
and uses a bounded buffer before decoding. Inbound request download currently has
a 30-second timeout; result download stays within the caller's pending deadline.

## Runtime, authorization and completion

Inside TelegramApp, the sending Bot comes from `TelegramDeps.message.bot`, and
PeerMiddleware supplies the app's `PeerHub` through a context variable. Outside a
handler supply both `bot=` and `hub=` explicitly and arrange for the existing
Dispatcher to feed replies through the same hub. A hub is not a poller. Never run
a competing `getUpdates` loop for peer traffic.

The run resolves a username if needed, sends one text message by default or one
envelope document when opted in, and waits asynchronously. The receiving peer must
answer as a Telegram reply anchored to that outbound message. Before any result
document download, the hub matches:

- receiving bot ID;
- private chat with sender ID equal to that chat ID;
- sender equal to the pending peer route;
- replied-to message authored by the receiving bot in the same private chat;
- replied-to message ID equal to the recorded outbound message ID;
- for envelope calls, a `result`/`error` caption with the pending request ID.

Replies arriving before the send returns wait for its real ID; they are not guessed
or matched by text. Concurrent calls match independently. Matched replies are
consumed before service forwarding, firewall, subscription and conversation routing.
Edited updates provide hub context (so editing a human prompt can delegate) but
never satisfy an outstanding peer answer.

**Default text mode:** the first correlated text or caption completes the result;
chunks are not assembled. A media-only matched update is consumed but does not
complete the wait. This mode does not return peer files.

**Multimodal mode:** text/captions, progress and unrelated documents do not complete
the wait. Only a fully downloaded, validated matching `result` or `error` envelope
completes it; an invalid expected envelope fails the call rather than returning
partial media. Duplicate/late responses are consumed while their correlation IDs
remain known. Empty result text is valid, including an attachments-only result.

On success, the caller gets `AgentRunResult[str]` with the text in `result.output`
and binaries in `result.response.files`. Received binaries also extend the caller's
`deps.attachments` when supplied, for the parent reply pipeline. Each peer call uses
a separate output queue so existing parent outputs are not echoed as peer inputs or
included in that child's response. The receiver serializes its full result text and
response files into one anchored result document; this avoids partial text/media
completion on the peer wire. Subsequent human-facing Telegram rendering is a separate
step, not a guarantee of byte-identical photo delivery.

## Access: requests are not responses

`TG_PEER_IDS` applies **only to unsolicited new inbound private bot requests**:
those with a listed sender and no `reply_to_message`. It is not an outbound peer
registry and not required to admit an answer to a registered/called peer.

For A delegating to B:

1. A registers B as a subagent. A does **not** need to duplicate B in `TG_PEER_IDS`
   merely to receive B's correlated answer.
2. If B runs Kibernikto, B opts into new requests from A with A's numeric ID in B's
   `TG_PEER_IDS`. B's regular firewall and subscription rules still apply.
3. For B independently initiating new tasks to A, configure A's inbound policy for B.
   That is a new direction of access, not response authorization.

In the normal Dispatcher path, new requests pass application middleware and the
private-peer request gate before envelope download. Unsupported request captions
are rejected before downloading. The download helper itself is not an authorization
boundary: call it only after access/correlation checks, and use Telegram Bot API
`getFile` paths, never sender-provided URLs or filesystem paths.

A listed sender is not automatically a private-firewall admin. Under `TG_PUBLIC=false`
only the configured master IDs currently pass; granting master access is broader
than a peer-only permission and must be deliberate. Subscription checks also remain
in force for new messages. Preserve application access controls when diagnosing delivery.

Unmatched private **bot replies** are not converted to new requests by the agent or
reply helper, even when the bot is in `TG_PEER_IDS`. This prevents response loops.
Group bots retain flat output and optional delay; they are not this private RPC path.

## Telegram-level Restrict Bot Usage

Project integration diagnosis confirmed that **Restrict Bot Usage was enabled on an
old, manually created bot**, not only on Managed Bots. Bot-to-Bot Mode and application
permissions alone did not resolve the delivery restriction. Removing the receiver's
Restrict Bot Usage restriction restored the verified round trip in **both directions**.
This is a recorded project result, not a live test performed by a documentation audit
or proof that the new multimodal protocol has passed live verification.

Check this setting separately from Bot-to-Bot Mode, firewall, peer opt-in and polling
health. Disabling it broadens Telegram-level access; obtain owner approval and preserve
application permissions. Do not promise that bot accounts can be added to its UI
allowlist without verifying the UI. Managed-bot management is not a prerequisite for
peer registration and does not grant control over old bots.

## Failure policy and durability limits

- **Per-process async wait, not durable execution.** Pending futures, downloads,
  active tasks and duplicate-suppression IDs live in the hub. No restart recovery,
  persisted mailbox, cross-worker ownership or deferred suspend/resume exists.
  Persisted SQL/chat history does not change this; atomic envelopes do not add
  durable or exactly-once execution.
- **No streaming.** No peer streaming-model implementation or progress protocol.
  Structured output, list-valued prompts, remote message history and
  `deferred_tool_results` resume are rejected. Include context in the prompt.
  Parent tools/capabilities/model overrides are not executed locally by the peer model.
- Timeout covers username resolution, sending, waiting and result download; shutdown
  cancels the tracked run. Cancelling a local wait does not cancel remote work already
  started. Pending capacity defaults to 256; completed-ID tombstones to 4096. Once
  evicted, old IDs are unknown. A send with no returned ID cannot be reliably
  deduplicated after an ambiguous transport failure.
- `PeerError` classifies rejected requests, rate limits, network interruption,
  timeout, protocol failures and explicit remote errors. It preserves the cause and
  records delivery as `not_sent` or `unknown`; rate limits include `retry_after`.
  No automatic resend occurs, especially after ambiguous delivery.
- A validated wire `error` becomes a terminal `PeerError(category='remote')`, never a
  successful textual answer. The receiver currently creates sanitized error envelopes
  for exceptions from its model/agent run. Errors before that run (including inbound
  download/deps construction), result encoding or reply delivery are not all covered
  by that error-envelope path. Remote silence/delivery failure can still end in a
  caller timeout; do not describe the wire error kind as universal recovery.

The adapter raises `PeerError(ToolFailed, UserError)`: ToolFailed provides native
`outcome='failed'` and direct-call exceptions; UserError is a narrow compatibility
marker that bypasses harness 0.18 generic crash containment. Do not use
SkipToolExecution as that marker: raw tool dispatch would misinterpret it as a
substitute successful result. Failure observations are not peer answers and do not
consume retry budget. A model may deliberately choose another action/new call.
Cancellation remains cancellation.

## Verification recipe

Run the skill checker via the
[isolated runbook](UTILS-AND-RUNNER.md#offline-verification). Offline tests use the
real Dispatcher, pydantic-ai and harness with fake network methods. Core coverage
includes `tests/test_peer_hub.py`, `tests/test_telegram_peer.py`,
`tests/test_peer_inbound.py`, `tests/test_peer_builder.py`,
`tests/test_peer_errors.py` and `tests/test_peer_example.py`. Multimodal coverage
includes `tests/test_peer_protocol.py`, `tests/test_peer_multimodal.py`,
`tests/test_peer_inputs.py`, `tests/test_peer_media_delivery.py` and
`tests/test_peer_wire_security.py`. File presence is not proof that every case passed.

Check bytes/MIME/name round trips, None/empty/explicit input selection, capture with
preprocessing disabled, attachments-only results, malformed/oversized envelopes,
authorization before downloads, progress ignored, complete result/error handling,
concurrent out-of-order answers, duplicates, timeout/cancellation/shutdown including
in-flight downloads, edited human delegation and failures through the real builder.
Keep default text-mode and preserved-local-expert regressions.

For authorized live verification, record each stage separately: parent tool call,
outbound Telegram delivery, remote Dispatcher receipt, remote model output, anchored
reply delivery and parent completion. Prove actual SubAgents delegation and inspect
both returned text and binaries; a one-way send or mock-only test is not live proof.
Verify both directions only if requested/configured. Never expose tokens or model keys.

The implementation is being updated concurrently: recheck prompt limits, capture
wiring and receiver error-envelope coverage against the final production diff before
calling this contract release-ready. This reference does not claim live multimodal
verification or document-parsing support.
