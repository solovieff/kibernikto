"""Library import hygiene and default constructor behavior."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic_ai.models.test import TestModel

REPO = Path(__file__).resolve().parents[1]


class LibraryImportsTests(unittest.TestCase):
    def _run_isolated(self, script: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as home:
            env = {
                "PATH": os.defpath,
                "HOME": home,
                "USERPROFILE": home,
                "PYTHONPATH": str(REPO),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHON_DOTENV_DISABLED": "1",
            }
            if "SYSTEMROOT" in os.environ:
                env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
            if extra_env:
                env.update(extra_env)
            return subprocess.run(
                [sys.executable, "-B", "-c", textwrap.dedent(script)],
                cwd=home,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

    def test_core_and_agent_package_import_without_telegram_or_provider_credentials(self) -> None:
        proc = self._run_isolated("""\
            import sys
            from kibernikto.ai.agent import build_kibernikto_agent, KiberniktoDeps
            from kibernikto.ai.agent.core import build_kibernikto_agent as core_builder, KiberniktoDeps as CoreDeps
            from kibernikto.ai.agent.core.kibernikto_agent import build_kibernikto_agent as direct_builder
            from kibernikto.ai.agent.harness import (
                ConversationMemory,
                CreditTier,
                KiberniktoSubAgents,
                chat_memory,
                web_layout,
            )

            assert ConversationMemory is not None
            assert CreditTier is not None
            assert chat_memory is not None

            assert build_kibernikto_agent is core_builder is direct_builder
            assert KiberniktoDeps is CoreDeps
            telegram_modules = [m for m in sys.modules if 'telegram' in m or m.startswith('aiogram')]
            assert not telegram_modules, f'Unexpected Telegram modules loaded: {telegram_modules}'
        """)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_telegram_agent_and_multi_agent_import_without_provider_credentials(self) -> None:
        proc = self._run_isolated("""\
            from kibernikto.ai.agent.telegram import TelegramAgent, TelegramDeps, get_telegram_agent, set_telegram_agent
            from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent, build_multi_agent_with_tg_peers

            assert TelegramAgent is not None
            assert TelegramDeps is not None
            assert callable(get_telegram_agent)
            assert callable(set_telegram_agent)
            assert callable(build_multi_agent)
            assert callable(build_multi_agent_with_tg_peers)
        """)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_build_kibernikto_agent_with_explicit_model_works_without_provider_credentials(self) -> None:
        proc = self._run_isolated("""\
            import asyncio
            from pathlib import Path
            from pydantic_ai.models.test import TestModel
            from kibernikto.ai.agent import build_kibernikto_agent

            agent = build_kibernikto_agent(model=TestModel(custom_output_text='ok'), name='lib_user')
            assert agent.name == 'lib_user'
            result = asyncio.run(agent.run('hello'))
            assert result.output == 'ok'
            assert not (Path.home() / '.kibernikto').exists()
        """)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_build_kibernikto_agent_defaults_from_settings_when_called_with_no_args(self) -> None:
        from kibernikto.ai.agent.core import kibernikto_agent as ka_mod
        from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
        from kibernikto.ai.agent.core.deps import KiberniktoDeps

        sentinel_model = TestModel()
        with patch.object(ka_mod, "build_kibernikto_model", return_value=sentinel_model) as build_m:
            agent = ka_mod.build_kibernikto_agent(history_storage=None)
        build_m.assert_called_once_with(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME, AGENT_KIBERNIKTO_SETTINGS.FALLBACK_MODELS)
        self.assertIs(agent.model, sentinel_model)
        self.assertEqual(agent.name, AGENT_KIBERNIKTO_SETTINGS.NAME)
        self.assertIs(agent.deps_type, KiberniktoDeps)
        self.assertEqual(agent.model_settings["max_tokens"], AGENT_KIBERNIKTO_SETTINGS.MODEL_MAX_TOKENS)
        self.assertEqual(agent.model_settings["temperature"], AGENT_KIBERNIKTO_SETTINGS.MODEL_TEMPERATURE)

    def test_build_kibernikto_agent_explicit_none_model_skips_default_inference(self) -> None:
        from kibernikto.ai.agent.core import kibernikto_agent as ka_mod

        with patch.object(ka_mod, "build_kibernikto_model") as build_m:
            agent = ka_mod.build_kibernikto_agent(model=None, history_storage=None)
        build_m.assert_not_called()
        self.assertIsNone(agent.model)

    def test_get_and_set_telegram_agent_lazy_default_and_swap(self) -> None:
        from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
        from kibernikto.ai.agent.telegram import telegram_agent as tg_mod

        sentinel_model = TestModel()
        previous = tg_mod._telegram_agent
        try:
            tg_mod._telegram_agent = None
            with patch.object(tg_mod, "build_kibernikto_model", return_value=sentinel_model) as build_m:
                default_agent = tg_mod.get_telegram_agent()
                second_call = tg_mod.get_telegram_agent()
            build_m.assert_called_once_with(AGENT_KIBERNIKTO_SETTINGS.MODEL_NAME, AGENT_KIBERNIKTO_SETTINGS.FALLBACK_MODELS)
            self.assertIs(default_agent, second_call)
            self.assertEqual(default_agent._metadata['reaction'], AGENT_KIBERNIKTO_SETTINGS.REACTION)

            custom = tg_mod.TelegramAgent(model=TestModel(), name="custom_tg", history_storage=None)
            returned_prev = tg_mod.set_telegram_agent(custom)
            self.assertIs(returned_prev, default_agent)
            self.assertIs(tg_mod.get_telegram_agent(), custom)
        finally:
            tg_mod._telegram_agent = previous


if __name__ == "__main__":
    unittest.main()
