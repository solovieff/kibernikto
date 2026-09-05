# Runtime, utilities and logging

This filename is retained for old links; the Telegram runner module was removed.
The current runtime is `kibernikto/telegram/agent/telegram_app.py`.

## Entry points and dotenv timing

`pyproject.toml` maps the `kibernikto` command to `kibernikto.cmd.__start:start`.
`main.py` calls `start(outer_env=False)`. `start` parses `--env_file_path` (default
`.env`) and `--multi-agent`, configures logging, prints the app/storage banner,
validates storage, optionally selects the local SubAgents parent, then calls the
active Telegram agent's `to_telegram().run_polling()`.

`kibernikto/cmd/__start.py` parses arguments and loads the selected dotenv file
before importing settings or agents. `--help` does not initialize providers or
load credentials. `outer_env=True` skips dotenv entirely. Existing environment
variables retain precedence in this CLI (`load_dotenv` does not override them).
Already-imported settings in an embedding process are not rebuilt: configure its
environment before importing configuration-dependent modules.

For authorized live use, run via `terminal` from the repository root:

```python
terminal(command=".venv/bin/python main.py", workdir="<repo>")
terminal(command=".venv/bin/python main.py --multi-agent", workdir="<repo>")
```

These are alternative launch commands, not simultaneous pollers. Use the existing
Windows venv `Scripts/python.exe` instead when applicable. Do not install or `uv sync`
without permission. `--multi-agent` enables local experts, not an env-driven peer registry.

## TelegramApp lifecycle

`TelegramAgent.to_telegram()` returns `TelegramApp.from_agent(self)`.
The app exposes synchronous `run_polling()` and async `start_polling()`; both use
its one Dispatcher/Bot. Call `set_telegram_agent` separately before polling.
Startup initializes SQL tables when selected, gets bot identity/descriptions, sets
identity instructions and optionally greets the master with a sticker. Shutdown
cancels peer runs and closes storage resources. See [Storage](STORAGE.md).

`validate_storage()` does the configured S3 HEAD request before CLI polling; SQL
initialization happens later in the polling event loop. File SQLite needs an existing
parent directory. Never call startup or validation during a secret-free docs import test.

## Reply and text utilities

`reply(message, content)` in `kibernikto/telegram/utils/conversation.py` accepts
str, `AgentRunResult` or None and returns the text portion sent. It reads
`result.output` and response images/files, not `result.data`.

- Text uses `split_text_by_sentences`, then Markdown-to-HTML by default, or legacy
  Markdown with `TG_MARKDOWN_TO_HTML=false`. Formatted-send errors retry plain text.
- Humans and opted-in private peer requests get anchored text replies; group bots
  post flat. Private bot replies/unknown new requests are suppressed by the reply helper.
- One image is sent with a caption; multiple/non-image attachments use media groups,
  with separate caption text. Captions are truncated to the module's 1023-character
  limit; do not promise preservation of a long accompanying answer or every media shape.
- The reply module has its own 4096/1023 constants. Settings with the same names do
  not currently override them.

`kibernikto/utils/text.py` contains `split_text(text, length=4096)` (fixed slices),
`split_text_by_sentences`, `clear_text_format`, `prepare_for_MARKDOWN` and
`markdown_to_html`. There is no `escape_markdown` API. The sentence splitter can
produce an oversized chunk for a single very long sentence and may produce empty
chunks; it is not a strict Telegram-limit guarantee.

## Images

Prefer `image_hosting.publish(image_bytes, name)` from
`kibernikto/utils/image_hosting.py`. The compatibility shim in
`kibernikto/utils/image.py` exposes `publish_image_file(image_bytes, name,
expiration=None)` and `post(filename, name)`; the per-call expiration argument is
ignored by the shim. Neither accepts a Bot/file ID. Settings and durable media
storage are explained in [Preprocessing](TELEGRAM-PREPROCESSING.md).

## Logging

`configure_logger()` and the app `print_banner()` live in `kibernikto/config.py`,
not the command module. Logfire uses the app instance name and
`send_to_logfire='if-token-present'`; pydantic-ai is instrumented and Python logging
uses a Logfire handler. The CLI banner prints app settings plus backend-relevant
storage fields with S3 credentials/DSN credentials masked. Agent and Telegram modules
have separate banner functions, but the CLI does not call all of them in sequence.
Do not dump the environment, unmasked settings, chat history or credential-bearing
Git configuration for diagnostics.

## Offline verification

1. Read `AGENTS.md` and `pyproject.toml`; use the existing interpreter without an IDE
   prerequisite. Project style targets 3.14+, while metadata says >=3.11. Report the
   interpreter actually used.
2. Use the helper shipped **inside this skill** through `terminal`:

```python
terminal(
    command=".venv/bin/python -B .agents/skills/kibernikto/scripts/check_docs.py",
    workdir="<repo>",
)
terminal(
    command=".venv/bin/python -B .agents/skills/kibernikto/scripts/check_docs.py --tests",
    workdir="<repo>",
)
```

The first verifies every skill Markdown file, relative links/anchors, literal source
paths (with explicit removed-path assertions), Python block syntax, actual snippet
imports, the core TestModel example and real SubAgent/peer builder construction.
The second additionally runs the repository's existing unittest discovery under
`tests/` (inspect newly added tests before running them).

The helper launches an isolated child with fake provider keys, temporary file storage,
a fresh home, no inherited API credentials, no dotenv loading, disabled model requests
and an audit hook blocking socket activity and common secret files. Temporary files
are confined to the skill directory and cleaned. It does not install dependencies,
start polling, call S3 validation or execute live-launch examples. No pytest install
is required by these unittest modules. Missing dependencies are a blocker to report,
not a reason to fabricate a successful import check.

The child also uses a temporary working directory: FastMCP's import-time settings
can read the cwd `.env` through `dotenv_values`, even with
`PYTHON_DOTENV_DISABLED=1`. The audit hook rejects that access before reading.
For unittest execution the helper permits explicit temporary env fixtures by removing
the dotenv-disable flag after import checks; live `.env` files remain blocked.

3. For edited examples, also exercise changed behavior with TestModel/FunctionModel,
   memory/temp storage and mocked Bot methods. Static import success does not prove
   live network behavior. See [Peer verification](TELEGRAM-PEERS.md#verification-recipe).
4. Inspect `git diff --check` and the scoped diff via `terminal`. Report changed files,
   checks and remaining limitations; no install, network run or commit is implied.
