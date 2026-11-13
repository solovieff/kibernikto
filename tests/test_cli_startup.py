"""Offline regressions for CLI argument parsing and environment timing."""

import builtins
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


REPO = Path(__file__).resolve().parents[1]


class CliHelpTests(unittest.TestCase):
    def test_help_needs_no_credentials_or_runtime_imports(self) -> None:
        script = textwrap.dedent("""\
            import os
            from pathlib import Path
            import runpy
            import sys

            repo, entry = sys.argv[1:]
            sys.path.insert(0, repo)

            def guard(event, args):
                if event in {'socket.connect', 'socket.getaddrinfo', 'socket.bind', 'socket.sendto'}:
                    raise AssertionError('CLI help attempted network access')
                if event == 'open' and isinstance(args[0], (str, bytes)):
                    path = Path(os.fsdecode(args[0]))
                    if path.name == '.env' or path.name.startswith('.env.'):
                        raise AssertionError('CLI help attempted dotenv access')
                if event == 'import' and args[0].startswith((
                    'kibernikto.ai', 'kibernikto.config',
                    'kibernikto.storage', 'kibernikto.telegram',
                )):
                    raise AssertionError('CLI help imported runtime configuration: ' + args[0])

            sys.addaudithook(guard)
            sys.argv = [entry, '--help']
            if entry == 'main.py':
                runpy.run_path(str(Path(repo) / entry), run_name='__main__')
            else:
                from kibernikto.cmd import start
                start()
            """)
        with tempfile.TemporaryDirectory(prefix="cli-help-") as tmp:
            env = {
                "PATH": os.defpath,
                "HOME": tmp,
                "USERPROFILE": tmp,
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            if "SYSTEMROOT" in os.environ:
                env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
            for entry in ("kibernikto", "main.py"):
                with self.subTest(entry=entry):
                    result = subprocess.run(
                        [sys.executable, "-B", "-c", script, str(REPO), entry],
                        cwd=tmp, env=env, capture_output=True, text=True, timeout=20,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("Run Kibernikto", result.stdout)
                    self.assertIn("--env_file_path", result.stdout)
                    self.assertIn("--multi-agent", result.stdout)
                    self.assertIn("--vkusvill", result.stdout)
                    self.assertEqual(result.stderr, "")


class AgentSummaryTests(unittest.TestCase):
    def test_summary_lists_models_without_secrets_or_personality(self) -> None:
        # Offline placeholders: importing the agent package needs a provider key, never a real one.
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-not-a-real-key',
                                     'AGENT_KIBERNIKTO_MODEL_NAME': 'openrouter:test/offline',
                                     'APP_STORAGE_DATA_BACKEND': 'file',
                                     'APP_STORAGE_MEDIA_BACKEND': 'file'}):
            from kibernikto.ai.agent.core.config import AgentKiberniktoSettings, agent_summary

        settings = AgentKiberniktoSettings(
            _env_file=None, MODEL_NAME='openrouter:m/main', POOR_MODEL='openrouter:m/poor',
            MEDIUM_MODEL='openrouter:m/medium', RICH_MODEL='openrouter:m/rich',
            WHO_AM_I='SECRET PERSONALITY TEXT',
        )
        summary = agent_summary('default', settings)
        self.assertEqual(summary['MODEL_NAME'], 'openrouter:m/main')
        self.assertEqual(summary['MEDIUM_MODEL'], 'openrouter:m/medium')
        self.assertEqual(summary['MODE'], 'default')
        self.assertNotIn('WHO_AM_I', summary)
        self.assertNotIn('SECRET PERSONALITY TEXT', str(summary))
        # Explicit secret-bearing field names; substring checks misfire on MODEL_MAX_TOKENS.
        forbidden = {'API_KEY', 'SECRET', 'ACCESS_KEY', 'PROVIDER_KEY', 'TOKEN'}
        self.assertFalse(forbidden & set(summary))


class CliStartupTests(unittest.TestCase):
    def run_startup(
        self, argv: list[str], *, outer_env: bool = False,
        initial_value: str | None = None,
    ) -> SimpleNamespace:
        events: list[tuple[str, str | None]] = []
        env_key = "CLI_STARTUP_TEST_VALUE"
        agents = {"default": Mock(), "multi-agent": Mock(), "vkusvill": Mock()}
        bridges = {name: Mock() for name in agents}
        apps = {name: Mock() for name in agents}
        poll_events = {"default": "poll_default", "multi-agent": "poll_multi", "vkusvill": "poll_vkusvill"}
        app_cls = Mock()
        app_cls.from_bridge.side_effect = lambda bridge: next(
            app for name, app in apps.items() if bridges[name] is bridge
        )

        def record(name: str) -> None:
            events.append((name, os.environ.get(env_key)))

        def load_env(dotenv_path: str = ".env") -> bool:
            record("dotenv:" + dotenv_path)
            os.environ.setdefault(env_key, "selected-file")
            return True

        def get_bridge() -> Mock:
            record("bridge")
            return bridges["default"]

        def bridge_factory(agent: object) -> Mock:
            record("bridge")
            return bridges[next(name for name, candidate in agents.items() if candidate is agent)]

        for name, app in apps.items():
            app.run_polling.side_effect = (lambda preset=poll_events[name]: record(preset))

        config = SimpleNamespace(
            configure_logger=lambda: record("logger"),
            print_banner=lambda: record("banner"),
        )
        runtime_modules = {
            "kibernikto.config": config,
            "kibernikto.ai.agent.core.config": SimpleNamespace(
                AGENT_KIBERNIKTO_SETTINGS=object(),
                print_agent_summary=lambda name: record("summary:" + name),
            ),
            "kibernikto.storage.config": SimpleNamespace(validate_storage=lambda: record("storage")),
            "kibernikto.telegram.agent.telegram_app": SimpleNamespace(TelegramApp=app_cls),
            "kibernikto.telegram.bridge": SimpleNamespace(
                TelegramBridge=bridge_factory, get_telegram_bridge=get_bridge,
            ),
            "kibernikto.ai.agent.telegram.multi_agent": SimpleNamespace(
                build_multi_agent=lambda: agents["multi-agent"],
            ),
            "kibernikto.ai.agent.addons.vkusvill": SimpleNamespace(
                build_vkusvill_agent=lambda: agents["vkusvill"],
            ),
        }
        root = SimpleNamespace(ai=SimpleNamespace(agent=SimpleNamespace(
            telegram=SimpleNamespace(telegram_agent=SimpleNamespace()),
        )))
        real_import = builtins.__import__

        def import_runtime(
            name: str, globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None, fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name in runtime_modules:
                record("import:" + name)
                return runtime_modules[name] if fromlist else root
            if name.startswith("kibernikto"):
                raise AssertionError("Unexpected real runtime import: " + name)
            return real_import(name, globals, locals, fromlist, level)

        spec = importlib.util.spec_from_file_location("cli_under_test", REPO / "kibernikto/cmd/__start.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        env = {env_key: initial_value} if initial_value is not None else {}
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["kibernikto", *argv]):
            with patch("dotenv.load_dotenv", side_effect=load_env) as loader:
                with patch("builtins.__import__", side_effect=import_runtime):
                    spec.loader.exec_module(module)
                    self.assertEqual(events, [], "Importing the CLI must not load env or runtime modules")
                    module.start(outer_env=outer_env)
        return SimpleNamespace(events=events, loader=loader, apps=apps)

    def test_custom_env_is_loaded_before_runtime_imports(self) -> None:
        result = self.run_startup(["--env_file_path", "custom.env"])
        result.loader.assert_called_once_with(dotenv_path="custom.env")
        self.assertEqual(result.events[0], ("dotenv:custom.env", None))
        self.assertTrue(all(value == "selected-file" for _, value in result.events[1:]))
        self.assertEqual([name for name, _ in result.events if not name.startswith("import:")], [
            "dotenv:custom.env", "logger", "banner", "storage", "bridge", "summary:default", "poll_default",
        ])
        result.apps["default"].run_polling.assert_called_once_with()
        result.apps["multi-agent"].run_polling.assert_not_called()

    def test_default_env_path_is_preserved(self) -> None:
        result = self.run_startup([])
        result.loader.assert_called_once_with(dotenv_path=".env")

    def test_outer_env_skips_all_dotenv_loading(self) -> None:
        result = self.run_startup(
            ["--env_file_path", "ignored.env"], outer_env=True, initial_value="external",
        )
        result.loader.assert_not_called()
        self.assertTrue(all(value == "external" for _, value in result.events))
        result.apps["default"].run_polling.assert_called_once_with()

    def test_multi_agent_registers_and_polls_selected_agent(self) -> None:
        result = self.run_startup(["--multi-agent"])
        result.loader.assert_called_once_with(dotenv_path=".env")
        self.assertIn(("import:kibernikto.ai.agent.telegram.multi_agent", "selected-file"), result.events)
        self.assertEqual([name for name, _ in result.events if not name.startswith("import:")], [
            "dotenv:.env", "logger", "banner", "storage", "bridge", "summary:multi-agent", "poll_multi",
        ])
        result.apps["default"].run_polling.assert_not_called()
        result.apps["multi-agent"].run_polling.assert_called_once_with()

    def test_vkusvill_registers_and_polls_the_shop_agent(self) -> None:
        result = self.run_startup(["--vkusvill"])
        self.assertIn(("import:kibernikto.ai.agent.addons.vkusvill", "selected-file"), result.events)
        self.assertEqual([name for name, _ in result.events if not name.startswith("import:")], [
            "dotenv:.env", "logger", "banner", "storage", "bridge", "summary:vkusvill", "poll_vkusvill",
        ])
        result.apps["multi-agent"].run_polling.assert_not_called()
        result.apps["vkusvill"].run_polling.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
