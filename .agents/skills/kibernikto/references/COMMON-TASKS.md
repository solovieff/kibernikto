# Common tasks

Use these recipes after reading the actual implementation; each has a completion check.

## Add a tool or expert

1. Read [Core agent](CORE-AGENT.md) and [Agents and harness](AGENTS-AND-HARNESS.md).
2. Add tools to a named `KiberniktoAgent` with compatible deps; decide whether it needs
   its own history namespace. Only an extended parent needs credit-tier behavior.
3. Register the expert with real `SubAgent(agent)` and verify its tool is reachable
   through the parent using a fake model. An imported module is not necessarily enabled.

## Add a Telegram peer

1. Read [Peers](TELEGRAM-PEERS.md); construct `TelegramPeerAgent` with a valid ID/name.
2. Use `build_subagents_agent_with_tg_peers(peers)` or ordinary SubAgents composition;
   register the parent separately before building/running the app.
3. Verify answers through the same Dispatcher with no duplicate response allowlist.
   Configure `TG_PEER_IDS` only for new inbound requests; prove the intended live
   direction separately when authorized. Do not call the unfinished error policy complete.

## Change storage or instructions

1. Read [Storage](STORAGE.md) and [Configuration](CONFIGURATION.md).
2. Configure data/media backends before imports. Use a named instruction file or
   WHO_AM_I for personality; instantiate again to pick up changed file contents.
3. Verify window alignment, persistence across fresh backend instances and no namespace
   crossover. For SQL ensure initialization on the application's event loop. Never
   inspect production chat data or keys merely to validate a docs example.

## Customize Telegram behavior

1. Read [Handlers](TELEGRAM-HANDLERS.md), [Preprocessing](TELEGRAM-PREPROCESSING.md)
   and [Middlewares](TELEGRAM-MIDDLEWARES.md) for the relevant observer.
2. Replace the active agent through the setter or add the correct router/middleware.
   Keep ordinary/edited messages and private/group bot traffic distinct.
3. Test content None/error cases, access denial, edited handling, matched-peer bypass
   and output rendering. Service forwarding currently excludes admins; obsolete debug
   notes are not a request to alter it.

## Work on payments or runtime

Read [Payments](PAYMENTS.md) before touching Stars access: no fulfillment router or
credit top-up is currently wired. Read [Runtime](UTILS-AND-RUNNER.md) before using
CLI env-file flags, running tests or starting a bot. Completion means actual offline
checks pass and remaining live/network-dependent checks are explicitly listed.
