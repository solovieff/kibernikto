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
                    self.assertEqual(result.stderr, "")


class CliStartupTests(unittest.TestCase):
    def run_startup(
        self, argv: list[str], *, outer_env: bool = False,
        initial_value: str | None = None,
    ) -> tuple[list[tuple[str, str | None]], Mock, Mock, Mock]:
        events: list[tuple[str, str | None]] = []
        env_key = "CLI_STARTUP_TEST_VALUE"
        default_app, multi_app = Mock(), Mock()
        default_agent = Mock(to_telegram=Mock(return_value=default_app))
        multi_agent = Mock(to_telegram=Mock(return_value=multi_app))
        telegram = SimpleNamespace(kibernikto_telegram_agent=default_agent)

        def record(name: str) -> None:
            events.append((name, os.environ.get(env_key)))

        def load_env(dotenv_path: str = ".env") -> bool:
            record("dotenv:" + dotenv_path)
            os.environ.setdefault(env_key, "selected-file")
            return True

        def set_agent(agent: object) -> None:
            record("set_agent")
            self.assertIs(agent, multi_agent)
            telegram.kibernikto_telegram_agent = agent

        telegram.set_telegram_agent = set_agent
        default_app.run_polling.side_effect = lambda: record("poll_default")
        multi_app.run_polling.side_effect = lambda: record("poll_multi")
        config = SimpleNamespace(
            configure_logger=lambda: record("logger"),
            print_banner=lambda: record("banner"),
        )
        runtime_modules = {
            "kibernikto.config": config,
            "kibernikto.ai.agent.core.config": SimpleNamespace(AGENT_KIBERNIKTO_SETTINGS=object()),
            "kibernikto.ai.agent.telegram.telegram_agent": telegram,
            "kibernikto.storage.config": SimpleNamespace(validate_storage=lambda: record("storage")),
            "kibernikto.ai.agent.extended.orchestrators": SimpleNamespace(
                kibernikto_subagents_agent=multi_agent,
            ),
        }
        root = SimpleNamespace(ai=SimpleNamespace(agent=SimpleNamespace(
            telegram=SimpleNamespace(telegram_agent=telegram),
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
        return events, loader, default_app, multi_app

    def test_custom_env_is_loaded_before_runtime_imports(self) -> None:
        events, loader, default_app, multi_app = self.run_startup(["--env_file_path", "custom.env"])
        loader.assert_called_once_with(dotenv_path="custom.env")
        self.assertEqual(events[0], ("dotenv:custom.env", None))
        self.assertTrue(all(value == "selected-file" for _, value in events[1:]))
        self.assertEqual([name for name, _ in events if not name.startswith("import:")], [
            "dotenv:custom.env", "logger", "banner", "storage", "poll_default",
        ])
        default_app.run_polling.assert_called_once_with()
        multi_app.run_polling.assert_not_called()

    def test_default_env_path_is_preserved(self) -> None:
        _, loader, _, _ = self.run_startup([])
        loader.assert_called_once_with(dotenv_path=".env")

    def test_outer_env_skips_all_dotenv_loading(self) -> None:
        events, loader, default_app, _ = self.run_startup(
            ["--env_file_path", "ignored.env"], outer_env=True, initial_value="external",
        )
        loader.assert_not_called()
        self.assertTrue(all(value == "external" for _, value in events))
        default_app.run_polling.assert_called_once_with()

    def test_multi_agent_registers_and_polls_selected_agent(self) -> None:
        events, loader, default_app, multi_app = self.run_startup(["--multi-agent"])
        loader.assert_called_once_with(dotenv_path=".env")
        self.assertIn(("import:kibernikto.ai.agent.extended.orchestrators", "selected-file"), events)
        self.assertEqual([name for name, _ in events if not name.startswith("import:")], [
            "dotenv:.env", "logger", "banner", "storage", "set_agent", "poll_multi",
        ])
        default_app.run_polling.assert_not_called()
        multi_app.run_polling.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
