# VkusVill agent (phase «a») Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a VkusVill shopping agent inside the kibernikto package that gets its 11 tools from the official MCP server and runs as the Telegram bot via `main.py --vkusvill`.

**Architecture:** A new package `kibernikto/ai/agent/vkusvill/` holds env settings, an `MCPToolset` factory (anonymous or OAuth 2.0 + PKCE with a file token store), the behaviour prompt, and `build_vkusvill_agent()` which delegates to the existing `build_telegram_agent()`. The CLI gains a `--vkusvill` switch that builds the bridge from that agent, so history, reactions, media and middleware stay stock.

**Tech Stack:** Python 3.14, pydantic-ai 2.55 (`MCPToolset`, `Agent`, `FunctionModel`), fastmcp 4.1.3 (`fastmcp.client.auth.OAuth`), py-key-value filetree store, pydantic-settings, aiogram v3, unittest.

**Spec:** `docs/superpowers/specs/2026-11-12-vkusvill-agent-design.md`

## Global Constraints

- MCP endpoint: `https://mcp.vkusvill.ru/mcp`; 11 tools; no order-placement tool exists — the flow always ends with a `https://vkusvill.ru/mobile?basket&share=...` link.
- Default `AGENT_VKUSVILL_AUTH_MODE` is `anonymous`; the agent must be usable without any VkusVill credentials.
- OAuth scopes: `catalog.search`, `purchase_history.read`, `discounts.view`, `recommendations.personalized`.
- Env prefix `AGENT_VKUSVILL_`; settings are env-only and fail fast on incomplete OAuth config.
- `AGENT_VKUSVILL_NAME` (default `vkusvill`) ends up in attribution HTTP headers — it must stay ASCII, the Russian identity lives in the prompt.
- Do not add dependencies (`FileTreeStore` from the already-installed `py-key-value-aio`; `DiskStore` is NOT available — it needs an extra package).
- No `__all__` in package `__init__.py`; relative imports only there.
- No `typing.Any`; use `str | None` style unions.
- Tests are `unittest`, offline, no network, no live credentials.
- Commands run from the repo root with the existing venv: `.venv/bin/python`.
- Do not push. Commit per task.

---

### Task 1: Settings and token directory

**Files:**
- Create: `kibernikto/ai/agent/vkusvill/__init__.py`
- Create: `kibernikto/ai/agent/vkusvill/config.py`
- Test: `tests/test_vkusvill_agent.py`

**Interfaces:**
- Produces:
  - `VkusvillSettings(BaseSettings)` with fields `NAME: str`, `MCP_URL: str`, `MODEL_NAME: str | None`, `AUTH_MODE: Literal['anonymous','oauth']`, `OAUTH_CLIENT_ID: str | None`, `OAUTH_CLIENT_SECRET: str | None`, `OAUTH_SCOPES: list[str]`, `OAUTH_CALLBACK_PORT: int`, `OAUTH_CALLBACK_HOST: str`, `OAUTH_TOKEN_DIR: str | None`.
  - `AGENT_VKUSVILL_SETTINGS: VkusvillSettings` module-level singleton.
  - `resolve_token_dir(settings: VkusvillSettings = AGENT_VKUSVILL_SETTINGS) -> Path`.
  - `DEFAULT_SCOPES: list[str]`, `DEFAULT_MCP_URL: str`.
- Consumes: `kibernikto.storage.config.STORAGE_SETTINGS.FILESTORE_LOCATION`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vkusvill_agent.py`:

```python
"""Offline coverage for the VkusVill MCP agent: settings, toolset wiring, behaviour prompt."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic import ValidationError

from kibernikto.ai.agent.vkusvill.config import (
    DEFAULT_MCP_URL,
    DEFAULT_SCOPES,
    VkusvillSettings,
    resolve_token_dir,
)


class VkusvillSettingsTests(unittest.TestCase):
    def test_defaults_are_anonymous(self) -> None:
        settings = VkusvillSettings()
        self.assertEqual(settings.AUTH_MODE, 'anonymous')
        self.assertEqual(settings.MCP_URL, DEFAULT_MCP_URL)
        self.assertEqual(settings.NAME, 'ВкусВилл')
        self.assertEqual(settings.OAUTH_SCOPES, DEFAULT_SCOPES)
        self.assertIsNone(settings.MODEL_NAME)

    def test_oauth_requires_credentials(self) -> None:
        with self.assertRaises(ValidationError):
            VkusvillSettings(AUTH_MODE='oauth')

    def test_oauth_accepts_full_credentials(self) -> None:
        settings = VkusvillSettings(AUTH_MODE='oauth', OAUTH_CLIENT_ID='cid', OAUTH_CLIENT_SECRET='secret')
        self.assertEqual(settings.OAUTH_CLIENT_ID, 'cid')

    def test_token_dir_defaults_under_filestore(self) -> None:
        settings = VkusvillSettings()
        with patch('kibernikto.ai.agent.vkusvill.config.STORAGE_SETTINGS') as storage:
            storage.FILESTORE_LOCATION = '/tmp/kibernikto-store'
            self.assertEqual(resolve_token_dir(settings), Path('/tmp/kibernikto-store/vkusvill-oauth'))

    def test_token_dir_honours_explicit_override(self) -> None:
        with TemporaryDirectory() as tmp:
            settings = VkusvillSettings(OAUTH_TOKEN_DIR=tmp)
            self.assertEqual(resolve_token_dir(settings), Path(tmp))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_vkusvill_agent -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kibernikto.ai.agent.vkusvill'`

- [ ] **Step 3: Write minimal implementation**

Create `kibernikto/ai/agent/vkusvill/config.py`:

```python
"""VkusVill shopping agent configuration — env-only via pydantic-settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kibernikto.storage.config import STORAGE_SETTINGS

DEFAULT_MCP_URL = 'https://mcp.vkusvill.ru/mcp'
DEFAULT_SCOPES = ['catalog.search', 'purchase_history.read', 'discounts.view', 'recommendations.personalized']
DEFAULT_TOKEN_DIRNAME = 'vkusvill-oauth'


class VkusvillSettings(BaseSettings):
    """VkusVill MCP endpoint, credentials and the OAuth callback."""

    model_config = SettingsConfigDict(env_prefix='AGENT_VKUSVILL_')

    NAME: str = Field(default='ВкусВилл', description='Agent name in logs and summaries')
    MCP_URL: str = Field(default=DEFAULT_MCP_URL, description='VkusVill MCP endpoint')
    MODEL_NAME: str | None = Field(
        default=None, description='Provider-prefixed model; unset = AGENT_KIBERNIKTO_MODEL_NAME',
    )
    AUTH_MODE: Literal['anonymous', 'oauth'] = Field(
        default='anonymous', description='anonymous: public catalog tools only; oauth: personalized tools',
    )
    OAUTH_CLIENT_ID: str | None = Field(default=None, description='From the VkusVill registration email')
    OAUTH_CLIENT_SECRET: str | None = Field(default=None, description='From the VkusVill registration email')
    OAUTH_SCOPES: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SCOPES), description='Requested OAuth scopes (JSON list in env)',
    )
    OAUTH_CALLBACK_PORT: int = Field(default=8765, description='Local OAuth callback port, must match redirect URI')
    OAUTH_CALLBACK_HOST: str = Field(default='localhost', description='Local OAuth callback host')
    OAUTH_TOKEN_DIR: str | None = Field(default=None, description='Token store dir; unset = FILESTORE/vkusvill-oauth')

    @model_validator(mode='after')
    def _validate_oauth_credentials(self) -> 'VkusvillSettings':
        if self.AUTH_MODE == 'oauth' and not (self.OAUTH_CLIENT_ID and self.OAUTH_CLIENT_SECRET):
            raise ValueError(
                'AGENT_VKUSVILL_AUTH_MODE=oauth requires AGENT_VKUSVILL_OAUTH_CLIENT_ID and AGENT_VKUSVILL_OAUTH_CLIENT_SECRET',
            )
        return self


AGENT_VKUSVILL_SETTINGS = VkusvillSettings()


def resolve_token_dir(settings: VkusvillSettings = AGENT_VKUSVILL_SETTINGS) -> Path:
    """Persistent OAuth token directory: explicit override or FILESTORE/vkusvill-oauth."""
    if settings.OAUTH_TOKEN_DIR:
        return Path(settings.OAUTH_TOKEN_DIR).expanduser()
    return Path(STORAGE_SETTINGS.FILESTORE_LOCATION).expanduser() / DEFAULT_TOKEN_DIRNAME
```

Create `kibernikto/ai/agent/vkusvill/__init__.py`:

```python
from .config import AGENT_VKUSVILL_SETTINGS, VkusvillSettings, resolve_token_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_vkusvill_agent -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add kibernikto/ai/agent/vkusvill tests/test_vkusvill_agent.py
git commit -m "feat(vkusvill): settings and oauth token directory"
```

---

### Task 2: MCP toolset factory

**Files:**
- Create: `kibernikto/ai/agent/vkusvill/mcp.py`
- Modify: `kibernikto/ai/agent/vkusvill/__init__.py`
- Test: `tests/test_vkusvill_agent.py`

**Interfaces:**
- Consumes: `VkusvillSettings`, `AGENT_VKUSVILL_SETTINGS`, `resolve_token_dir`.
- Produces: `build_vkusvill_toolset(settings: VkusvillSettings = AGENT_VKUSVILL_SETTINGS) -> MCPToolset[object]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_vkusvill_agent.py`:

```python
class VkusvillToolsetTests(unittest.TestCase):
    def test_anonymous_toolset_points_at_the_public_endpoint(self) -> None:
        toolset = build_vkusvill_toolset()
        self.assertIsInstance(toolset, MCPToolset)
        self.assertEqual(str(toolset.client.transport.url), DEFAULT_MCP_URL)

    def test_oauth_toolset_carries_credentials_and_creates_the_token_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            token_dir = Path(tmp) / 'tokens'
            settings = VkusvillSettings(
                AUTH_MODE='oauth',
                OAUTH_CLIENT_ID='cid',
                OAUTH_CLIENT_SECRET='secret',
                OAUTH_TOKEN_DIR=str(token_dir),
            )
            toolset = build_vkusvill_toolset(settings)
            auth = toolset.client.transport.auth
            self.assertIsInstance(auth, OAuth)
            self.assertEqual(auth._static_client_info.client_id, 'cid')  # noqa: SLF001 — public shape is not exposed
            self.assertTrue(token_dir.is_dir())
```

Add the imports at the top of the same file (after the `pydantic` import block):

```python
from fastmcp.client.auth import OAuth
from pydantic_ai.mcp import MCPToolset

from kibernikto.ai.agent.vkusvill.mcp import build_vkusvill_toolset
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_vkusvill_agent -v`
Expected: FAIL with `ImportError: cannot import name 'build_vkusvill_toolset'`

- [ ] **Step 3: Write minimal implementation**

Create `kibernikto/ai/agent/vkusvill/mcp.py`:

```python
"""VkusVill MCP toolset factory — anonymous catalog access or OAuth 2.0 + PKCE."""

from fastmcp.client.auth import OAuth
from key_value.aio.stores.filetree import FileTreeStore
from pydantic_ai.mcp import MCPToolset

from .config import AGENT_VKUSVILL_SETTINGS, VkusvillSettings, resolve_token_dir


def build_vkusvill_toolset(settings: VkusvillSettings = AGENT_VKUSVILL_SETTINGS) -> MCPToolset[object]:
    """Tools from mcp.vkusvill.ru; the token store survives restarts in oauth mode."""
    if settings.AUTH_MODE == 'anonymous':
        return MCPToolset(settings.MCP_URL)

    token_dir = resolve_token_dir(settings)
    token_dir.mkdir(parents=True, exist_ok=True)
    # fastmcp OAuth is an httpx.Auth subclass, so it satisfies MCPToolset's auth parameter directly.
    oauth = OAuth(
        mcp_url=settings.MCP_URL,
        client_id=settings.OAUTH_CLIENT_ID,
        client_secret=settings.OAUTH_CLIENT_SECRET,
        scopes=list(settings.OAUTH_SCOPES),
        callback_port=settings.OAUTH_CALLBACK_PORT,
        callback_host=settings.OAUTH_CALLBACK_HOST,
        token_storage=FileTreeStore(data_directory=token_dir),
    )
    return MCPToolset(settings.MCP_URL, auth=oauth)
```

Extend `kibernikto/ai/agent/vkusvill/__init__.py`:

```python
from .config import AGENT_VKUSVILL_SETTINGS, VkusvillSettings, resolve_token_dir
from .mcp import build_vkusvill_toolset
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_vkusvill_agent -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add kibernikto/ai/agent/vkusvill tests/test_vkusvill_agent.py
git commit -m "feat(vkusvill): mcp toolset factory with anonymous and oauth modes"
```

---

### Task 3: Behaviour prompt and agent builder

**Files:**
- Create: `kibernikto/ai/agent/vkusvill/prompts.py`
- Create: `kibernikto/ai/agent/vkusvill/agent.py`
- Modify: `kibernikto/ai/agent/vkusvill/__init__.py`
- Test: `tests/test_vkusvill_agent.py`

**Interfaces:**
- Consumes: `build_vkusvill_toolset`, `AGENT_VKUSVILL_SETTINGS`, `build_telegram_agent`, `infer_kibernikto_model`, `history_storage` singleton.
- Produces:
  - `AGENT_VKUSVILL_INSTRUCTIONS: str`
  - `build_vkusvill_agent(*, history_storage: HistoryStorage | None = history_storage, toolset: AbstractToolset | None = None, settings: VkusvillSettings = AGENT_VKUSVILL_SETTINGS, **kwargs) -> Agent[TelegramDeps]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_vkusvill_agent.py`:

```python
class ScriptedModel:
    """Answers `ok` and records every request so instructions can be inspected."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(messages[-1])
        return ModelResponse(parts=[TextPart('ok')])


class VkusvillAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.model = ScriptedModel()
        self.toolset = MCPToolset('http://localhost:1/mcp')
        self.agent = build_vkusvill_agent(
            model=FunctionModel(self.model),
            toolset=self.toolset,
            history_storage=None,
        )

    async def test_agent_is_named_and_owns_the_mcp_toolset(self) -> None:
        self.assertEqual(self.agent.name, 'ВкусВилл')
        self.assertIn(self.toolset, self.agent.toolsets)

    async def test_instructions_carry_the_shopping_contract(self) -> None:
        await self.agent.run('привет', deps=TelegramDeps())
        instructions = self.model.requests[-1].instructions or ''
        self.assertIn('ВкусВилл', instructions)
        self.assertIn('vkusvill_cart_link_create', instructions)
        self.assertIn('vkusvill.ru/mobile?basket&share=', instructions)
        self.assertIn('не оформляешь заказ', instructions)

    async def test_generic_persona_is_not_injected(self) -> None:
        await self.agent.run('привет', deps=TelegramDeps())
        instructions = self.model.requests[-1].instructions or ''
        self.assertNotIn('Kibernikto', instructions)
```

Add the imports at the top of the same file:

```python
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.vkusvill.agent import build_vkusvill_agent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_vkusvill_agent -v`
Expected: FAIL with `ImportError: cannot import name 'build_vkusvill_agent'`

- [ ] **Step 3: Write minimal implementation**

Create `kibernikto/ai/agent/vkusvill/prompts.py`:

```python
"""Behaviour contract for the VkusVill shopping agent."""

AGENT_VKUSVILL_INSTRUCTIONS = """
Ты — помощник интернет-магазина ВкусВилл. Помогаешь выбрать продукты и собрать корзину.

Правила:
1. О товарах сообщай только то, что вернули инструменты: название, цену, рейтинг, состав, КБЖУ.
   Не выдумывай товары, цены и наличие.
2. На запрос «собери корзину» предложи до трёх вариантов из реальных результатов поиска:
   «Выгодно» — самая низкая цена, «Любимое» — самый высокий рейтинг, «Лайт» — наименьшая калорийность.
3. Корзину собирай инструментом vkusvill_cart_link_create: products = [{"id": <id товара>, "q": <количество>}],
   где q — число от 0.01 до 40.
4. Каждый вариант заканчивай ссылкой из поля link и фразой: цены, наличие и состав уточняй на карточках товаров.
5. Ты не оформляешь заказ: ссылку открывает и подтверждает человек.
   Никогда не утверждай, что заказ размещён, оплачен или принят в сборку.
6. Цены называй в рублях. Если инструмент вернул ошибку — скажи об этом прямо,
   не подменяй её выдуманными товарами.
""".strip()
```

Create `kibernikto/ai/agent/vkusvill/agent.py`:

```python
"""build_vkusvill_agent — plain Agent[TelegramDeps] wired to the VkusVill MCP toolset."""

from pydantic_ai import Agent
from pydantic_ai.toolsets import AbstractToolset

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent
from kibernikto.ai.agent.utils import infer_kibernikto_model
from kibernikto.storage.base import HistoryStorage
from kibernikto.storage.singletons import history_storage

from .config import AGENT_VKUSVILL_SETTINGS, VkusvillSettings
from .mcp import build_vkusvill_toolset
from .prompts import AGENT_VKUSVILL_INSTRUCTIONS


def build_vkusvill_agent(
        *,
        history_storage: HistoryStorage | None = history_storage,
        toolset: AbstractToolset | None = None,
        settings: VkusvillSettings = AGENT_VKUSVILL_SETTINGS,
        **kwargs,
) -> Agent[TelegramDeps]:
    """Shop assistant for Telegram: stock transport and history, VkusVill identity and tools."""
    if settings.MODEL_NAME is not None:
        kwargs.setdefault('model', infer_kibernikto_model(settings.MODEL_NAME))
    return build_telegram_agent(
        history_storage=history_storage,
        name=settings.NAME,
        persona=False,
        instructions=AGENT_VKUSVILL_INSTRUCTIONS,
        toolsets=[toolset or build_vkusvill_toolset(settings)],
        **kwargs,
    )
```

Extend `kibernikto/ai/agent/vkusvill/__init__.py`:

```python
from .agent import build_vkusvill_agent
from .config import AGENT_VKUSVILL_SETTINGS, VkusvillSettings, resolve_token_dir
from .mcp import build_vkusvill_toolset
from .prompts import AGENT_VKUSVILL_INSTRUCTIONS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_vkusvill_agent -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add kibernikto/ai/agent/vkusvill tests/test_vkusvill_agent.py
git commit -m "feat(vkusvill): agent builder with shopping prompt"
```

---

### Task 4: CLI switch

**Files:**
- Modify: `kibernikto/cmd/__start.py`
- Test: `tests/test_cli_startup.py`

**Interfaces:**
- Produces: `build_bridge(multi_agent: bool, vkusvill: bool) -> tuple[TelegramBridge, str]` in `kibernikto/cmd/__start.py`.
- Consumes: `build_vkusvill_agent`, `build_multi_agent`, `get_telegram_bridge`.

- [ ] **Step 1: Write the failing test**

In `tests/test_cli_startup.py`, inside `CliHelpTests.test_help_needs_no_credentials_or_runtime_imports`, after the `--multi-agent` assertion add:

```python
                    self.assertIn("--vkusvill", result.stdout)
```

Append a new test class at the end of the file:

```python
class BridgeRoutingTests(unittest.TestCase):
    def test_vkusvill_flag_wins_over_multi_agent(self) -> None:
        from kibernikto.cmd.__start import build_bridge

        with patch('kibernikto.ai.agent.vkusvill.build_vkusvill_agent', return_value=Mock()) as builder:
            with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-not-a-real-key',
                                         'AGENT_KIBERNIKTO_MODEL_NAME': 'openrouter:test/offline',
                                         'APP_STORAGE_DATA_BACKEND': 'file',
                                         'APP_STORAGE_MEDIA_BACKEND': 'file'}):
                _, label = build_bridge(multi_agent=True, vkusvill=True)
        self.assertEqual(label, 'vkusvill')
        builder.assert_called_once_with()

    def test_default_route_uses_the_registered_bridge(self) -> None:
        from kibernikto.cmd.__start import build_bridge

        sentinel = Mock()
        with patch('kibernikto.telegram.bridge.get_telegram_bridge', return_value=sentinel):
            bridge, label = build_bridge(multi_agent=False, vkusvill=False)
        self.assertEqual(label, 'default')
        self.assertIs(bridge, sentinel)
```

`Mock` is already imported in that file (`from unittest.mock import Mock, patch`); if not, add it.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_cli_startup -v`
Expected: FAIL — `ImportError: cannot import name 'build_bridge'` and the `--vkusvill` help assertion fails.

- [ ] **Step 3: Write minimal implementation**

Rewrite `kibernikto/cmd/__start.py`:

```python
import argparse
from dotenv import load_dotenv


def build_bridge(multi_agent: bool = False, vkusvill: bool = False):
    """Pick the agent for this process; the Telegram transport is identical for every preset."""
    from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent
    from kibernikto.telegram.bridge import TelegramBridge, get_telegram_bridge

    if vkusvill:
        from kibernikto.ai.agent.vkusvill import build_vkusvill_agent

        return TelegramBridge(build_vkusvill_agent()), 'vkusvill'
    if multi_agent:
        return TelegramBridge(build_multi_agent()), 'multi-agent'
    return get_telegram_bridge(), 'default'


def start(outer_env=False):
    """Build the Telegram bot and start polling."""
    parser = argparse.ArgumentParser(description='Run Kibernikto')
    parser.add_argument('--env_file_path', metavar='env_file_path', required=False,
                        help='env file location', default='.env')
    parser.add_argument('--multi-agent', action='store_true', required=False,
                        help='use multi-agent system with subagent delegation', default=False)
    parser.add_argument('--vkusvill', action='store_true', required=False,
                        help='run the VkusVill shopping agent instead of the default one', default=False)

    args = parser.parse_args()

    if not outer_env:
        load_dotenv(dotenv_path=args.env_file_path)

    # Runtime imports construct settings and providers from the selected environment.
    from kibernikto.config import configure_logger, print_banner

    configure_logger()
    print_banner()

    from kibernikto.storage.config import validate_storage
    validate_storage()

    from kibernikto.ai.agent.core.config import print_agent_summary
    from kibernikto.telegram.agent.telegram_app import TelegramApp

    bridge, preset = build_bridge(multi_agent=args.multi_agent, vkusvill=args.vkusvill)
    print_agent_summary(preset)

    TelegramApp.from_bridge(bridge).run_polling()


if __name__ == '__main__':
    start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_cli_startup -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kibernikto/cmd/__start.py tests/test_cli_startup.py
git commit -m "feat(cli): --vkusvill preset for the telegram bot"
```

---

### Task 5: Example, docs and full gate

**Files:**
- Create: `examples/vkusvill_agent.py`
- Modify: `deploy/tg_bots/kibernikto/kibernikto.env`
- Modify: `AGENTS.md`
- Modify: `.agents/skills/kibernikto/SKILL.md`
- Modify: `docs/superpowers/specs/2026-11-12-vkusvill-agent-design.md` (token dir name)

**Interfaces:**
- Consumes: `build_vkusvill_agent`, `MemoryHistoryStorage`.

- [ ] **Step 1: Write the example**

Create `examples/vkusvill_agent.py`:

```python
"""VkusVill shopping agent without Telegram: python examples/vkusvill_agent.py"""

import asyncio

from kibernikto.ai.agent.vkusvill import build_vkusvill_agent
from kibernikto.storage.base import MemoryHistoryStorage


async def main() -> None:
    agent = build_vkusvill_agent(history_storage=MemoryHistoryStorage())
    while True:
        prompt = input('Ты: ').strip()
        if prompt in {'выход', 'exit', 'quit'}:
            return
        result = await agent.run(prompt, conversation_id='vkusvill-demo')
        print(f'ВкусВилл: {result.output}')


if __name__ == '__main__':
    asyncio.run(main())
```

Verify `MemoryHistoryStorage` accepts a no-argument constructor with `.venv/bin/python -c "from kibernikto.storage.base import MemoryHistoryStorage; MemoryHistoryStorage()"`; if it requires `history_size`, pass `MemoryHistoryStorage(history_size=20)`.

- [ ] **Step 2: Document the env block**

Append to `deploy/tg_bots/kibernikto/kibernikto.env`:

```
########################
# VKUSVILL — shopping agent (main.py --vkusvill) over https://mcp.vkusvill.ru/mcp
# AUTH_MODE=anonymous: public catalog tools, cart is returned as a share link.
# AUTH_MODE=oauth: register a client at https://vkusvill.ru/oauth/registration/ and paste the
#                  credentials from the email; the first run opens the browser for the callback.
########################
# AGENT_VKUSVILL_NAME=ВкусВилл
# AGENT_VKUSVILL_MCP_URL=https://mcp.vkusvill.ru/mcp
# AGENT_VKUSVILL_AUTH_MODE=anonymous
# AGENT_VKUSVILL_MODEL_NAME=
# AGENT_VKUSVILL_OAUTH_CLIENT_ID=
# AGENT_VKUSVILL_OAUTH_CLIENT_SECRET=
# AGENT_VKUSVILL_OAUTH_SCOPES=["catalog.search","purchase_history.read","discounts.view","recommendations.personalized"]
# AGENT_VKUSVILL_OAUTH_CALLBACK_PORT=8765
# AGENT_VKUSVILL_OAUTH_CALLBACK_HOST=localhost
# AGENT_VKUSVILL_OAUTH_TOKEN_DIR=
```

- [ ] **Step 3: Update the architecture docs**

In `AGENTS.md`, under `### Architecture Layers`, add after the `kibernikto.ai.agent` sub-tree lines:

```
  │     ├── vkusvill/ (build_vkusvill_agent: MCPToolset over mcp.vkusvill.ru + shopping prompt;
  │     │              AGENT_VKUSVILL_* settings, anonymous or OAuth 2.0 + PKCE)
```

and under `### Agent Patterns` add:

```
- VkusVill: `main.py --vkusvill` swaps the agent, the transport stays stock; tools come from `MCPToolset`
  (`kibernikto/ai/agent/vkusvill/mcp.py`). There is no order tool upstream — the flow ends with a cart share link.
```

In `.agents/skills/kibernikto/SKILL.md`, add a row to the source map table after the multi-agent row:

```
| VkusVill MCP agent (`main.py --vkusvill`) | `kibernikto/ai/agent/vkusvill/` |
```

- [ ] **Step 4: Align the spec**

In `docs/superpowers/specs/2026-11-12-vkusvill-agent-design.md`, replace
`{APP_STORAGE_FILESTORE_LOCATION}/{NAME}-oauth` with `{APP_STORAGE_FILESTORE_LOCATION}/vkusvill-oauth`.

- [ ] **Step 5: Run the full gate**

```bash
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/ruff check .
.venv/bin/python -B .agents/skills/kibernikto/scripts/check_docs.py --tests
```

Expected: full suite green (365+ tests), ruff clean, doc check green.

- [ ] **Step 6: Commit**

```bash
git add examples/vkusvill_agent.py deploy/tg_bots/kibernikto/kibernikto.env AGENTS.md \
        .agents/skills/kibernikto/SKILL.md docs/superpowers/specs/2026-11-12-vkusvill-agent-design.md
git commit -m "docs(vkusvill): example, env block and architecture notes"
```

---

### Task 6: Live acceptance gate (manual, by the user)

**Files:** none.

- [ ] **Step 1: Start the bot**

```bash
cd ~/kibernikto && .venv/bin/python main.py --vkusvill
```

- [ ] **Step 2: Send in Telegram**

Prompt: «собери корзину: круассан, сырники, сметана, сгущёнка, голубика, кофе в дрип-пакетах, апельсиновый сок».

Expected: tool calls to `vkusvill_products_search`, then a `vkusvill_cart_link_create` result rendered as
`https://vkusvill.ru/mobile?basket&share=...` plus the disclaimer. Opening the link shows the products.

- [ ] **Step 3: Record the verdict**

Only after the user confirms the link opens and the basket is correct, the phase «a» is done.
OAuth (`AGENT_VKUSVILL_AUTH_MODE=oauth`) is tested separately once credentials arrive by email.

---

## Self-Review

- Spec coverage: module layout (tasks 1–3), config table (task 1), toolset factory (task 2), prompt contract (task 3), run path (task 4), docs and example (task 5), OAuth lifecycle (task 2 + task 6 note), testing (every task), live gate (task 6). Non-goals untouched.
- Placeholders: none — every step ships runnable code and exact commands.
- Type consistency: `build_vkusvill_toolset`, `build_vkusvill_agent`, `VkusvillSettings`, `resolve_token_dir`, `build_bridge` are used with the same signatures in every task.
