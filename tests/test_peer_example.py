"""Offline contract tests for the public Telegram peers launcher."""
from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
import importlib
import os
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, patch
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PeerExampleTests(unittest.TestCase):
    def startup_fixture(self, *, backend: str = 'file', sqlite_path: str = ':memory:') -> SimpleNamespace:
        stack = self.enterContext(ExitStack())
        directory = Path(stack.enter_context(TemporaryDirectory()))
        env_file = directory / 'bot.env'
        env_file.write_text('PEER_EXAMPLE_SENTINEL=loaded\n', encoding='utf-8')
        stack.enter_context(patch.dict(os.environ, {'PEER_EXAMPLE_SENTINEL': 'inherited'}))
        settings = SimpleNamespace(DATA_BACKEND=backend, SQLITE_PATH=sqlite_path)
        events = Mock()
        agent = Mock(capture_peer_media=False)
        events.attach_mock(agent.to_telegram.return_value.run_polling, 'poll')
        peer_factory = Mock(return_value=object())
        builder = Mock(return_value=agent)
        worker_factory = Mock(return_value=agent)
        model = object()
        model_settings = object()
        exports = {
            'kibernikto.config': {'configure_logger': events.configure_logger},
            'kibernikto.storage.config': {
                'STORAGE_SETTINGS': settings, 'validate_storage': events.validate,
            },
            'kibernikto.ai.agent.core.config': {
                'AGENT_KIBERNIKTO_SETTINGS': SimpleNamespace(NAME='configured_bot'),
            },
            'kibernikto.ai.agent.core.kibernikto_agent': {
                'model': model, 'model_settings': model_settings,
            },
            'kibernikto.ai.agent.telegram.telegram_agent': {
                'TelegramAgent': worker_factory, 'set_telegram_agent': events.register,
            },
            'kibernikto.ai.agent.telegram.peer_agent': {'TelegramPeerAgent': peer_factory},
            'kibernikto.ai.agent.extended.orchestrators': {
                'build_subagents_agent_with_tg_peers': builder,
            },
        }
        modules: dict[str, ModuleType] = {}
        for name, attributes in exports.items():
            module = ModuleType(name)
            module.__dict__.update(attributes)
            modules[name] = module
        stack.enter_context(patch.dict(sys.modules, modules))
        imported: list[str] = []
        original_import = builtins.__import__

        def guarded_import(
            name: str, globals: Mapping[str, object] | None = None,
            locals: Mapping[str, object] | None = None,
            fromlist: Sequence[str] = (), level: int = 0,
        ) -> ModuleType:
            if name.startswith('kibernikto'):
                self.assertEqual(os.environ.get('PEER_EXAMPLE_SENTINEL'), 'loaded')
                imported.append(name)
            return original_import(name, globals, locals, fromlist, level)

        stack.enter_context(patch('builtins.__import__', side_effect=guarded_import))
        example = importlib.import_module('examples.telegram_peers')
        return SimpleNamespace(
            example=example, directory=directory, env_file=env_file,
            settings=settings, events=events, agent=agent, peer_factory=peer_factory,
            builder=builder, worker_factory=worker_factory, model=model,
            model_settings=model_settings, imported=imported,
        )

    def test_worker_registers_configured_agent_then_polls_without_delegation(self) -> None:
        fixture = self.startup_fixture()
        fixture.example.main(['--env-file', str(fixture.env_file)])
        fixture.worker_factory.assert_called_once_with(
            model=fixture.model, model_settings=fixture.model_settings, name='configured_bot',
        )
        fixture.builder.assert_not_called()
        fixture.peer_factory.assert_not_called()
        self.assertNotIn('kibernikto.ai.agent.extended.orchestrators', fixture.imported)
        self.assertEqual(fixture.events.mock_calls, [call.configure_logger(), call.validate(), call.register(fixture.agent), call.poll()])
        fixture.agent.to_telegram.assert_called_once_with()
        fixture.agent.run.assert_not_called()
        self.assertIs(fixture.agent.capture_peer_media, False)

    def test_caller_builds_poetry_peer_with_public_builder(self) -> None:
        fixture = self.startup_fixture()
        fixture.example.main(['--env-file', str(fixture.env_file), '--peer', '@ExamplePoetBot'])
        fixture.peer_factory.assert_called_once_with(
            peer='@ExamplePoetBot', name='poet',
            description='Пишет стихи по заданной теме, размеру и настроению.',
        )
        fixture.builder.assert_called_once_with([fixture.peer_factory.return_value])
        fixture.worker_factory.assert_not_called()
        self.assertEqual(fixture.events.mock_calls, [call.configure_logger(), call.validate(), call.register(fixture.agent), call.poll()])
        fixture.agent.run.assert_not_called()
        self.assertIs(fixture.agent.capture_peer_media, False)

    def test_multimodal_caller_opts_peer_into_binary_transport(self) -> None:
        fixture = self.startup_fixture()
        fixture.example.main([
            '--env-file', str(fixture.env_file), '--peer', '@ExamplePoetBot', '--multimodal',
        ])
        fixture.peer_factory.assert_called_once_with(
            peer='@ExamplePoetBot', name='poet',
            description='Пишет стихи по заданной теме, размеру и настроению.', multimodal=True,
        )
        fixture.builder.assert_called_once_with([fixture.peer_factory.return_value])
        fixture.worker_factory.assert_not_called()
        fixture.agent.run.assert_not_called()

    def test_multimodal_caller_captures_current_media_before_registration(self) -> None:
        fixture = self.startup_fixture()
        fixture.events.register.side_effect = lambda agent: self.assertIs(agent.capture_peer_media, True)
        fixture.example.main([
            '--env-file', str(fixture.env_file), '--peer', '@ExamplePoetBot', '--multimodal',
        ])
        self.assertIs(fixture.agent.capture_peer_media, True)
        fixture.events.register.assert_called_once_with(fixture.agent)
        fixture.agent.to_telegram.return_value.run_polling.assert_called_once_with()

    def test_multimodal_without_peer_is_rejected_before_loading_environment(self) -> None:
        fixture = self.startup_fixture()
        with patch('sys.stderr'), self.assertRaises(SystemExit) as error:
            fixture.example.main(['--env-file', str(fixture.env_file), '--multimodal'])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(fixture.imported, [])
        self.assertEqual(os.environ['PEER_EXAMPLE_SENTINEL'], 'inherited')
        fixture.worker_factory.assert_not_called()
        fixture.events.register.assert_not_called()

    def test_worker_instructions_configure_the_actual_agent(self) -> None:
        fixture = self.startup_fixture()
        instructions = 'Ты поэт. Пиши стихи по теме, размеру и настроению из запроса.'
        fixture.example.main(['--env-file', str(fixture.env_file), '--instructions', instructions])
        fixture.agent.instructions.assert_called_once_with(instructions)

    def test_sqlite_parent_is_created_before_storage_validation(self) -> None:
        fixture = self.startup_fixture(backend='sqlite')
        database = fixture.directory / 'nested' / 'storage' / 'bot.sqlite3'
        fixture.settings.SQLITE_PATH = str(database)
        fixture.events.validate.side_effect = lambda: self.assertTrue(database.parent.is_dir())
        fixture.example.main(['--env-file', str(fixture.env_file)])
        self.assertFalse(database.exists())

    def test_numeric_peer_and_custom_metadata_reach_the_builder(self) -> None:
        fixture = self.startup_fixture()
        fixture.example.main([
            '--env-file', str(fixture.env_file), '--peer', '123456',
            '--peer-name', 'sonnet_poet', '--peer-description', 'Writes sonnets',
        ])
        fixture.peer_factory.assert_called_once_with(peer=123456, name='sonnet_poet', description='Writes sonnets')

    def test_invalid_peer_is_rejected_before_loading_environment(self) -> None:
        fixture = self.startup_fixture()
        for peer in ('0', '-1', '123abc', 'ExamplePoetBot', '@x', ' @ExamplePoetBot'):
            with self.subTest(peer=peer), patch('sys.stderr'):
                with self.assertRaises(SystemExit) as error:
                    fixture.example.main(['--env-file', str(fixture.env_file), '--peer', peer])
                self.assertEqual(error.exception.code, 2)
        self.assertEqual(fixture.imported, [])
        self.assertEqual(os.environ['PEER_EXAMPLE_SENTINEL'], 'inherited')

    def test_missing_env_file_fails_before_framework_import(self) -> None:
        fixture = self.startup_fixture()
        with patch('sys.stderr'), self.assertRaises(SystemExit) as error:
            fixture.example.main(['--env-file', str(fixture.directory / 'missing.env')])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(fixture.imported, [])
        fixture.agent.to_telegram.assert_not_called()

    def test_in_memory_sqlite_does_not_create_directories(self) -> None:
        fixture = self.startup_fixture(backend='sqlite')
        with patch.object(Path, 'mkdir') as mkdir:
            fixture.example.main(['--env-file', str(fixture.env_file)])
        mkdir.assert_not_called()

    def test_failed_storage_validation_never_launches_polling(self) -> None:
        fixture = self.startup_fixture()
        fixture.events.validate.side_effect = OSError('offline storage failure')
        with self.assertRaisesRegex(OSError, 'offline storage failure'):
            fixture.example.main(['--env-file', str(fixture.env_file)])
        fixture.events.register.assert_not_called()
        fixture.agent.to_telegram.assert_not_called()

    def test_env_file_is_required_without_importing_framework(self) -> None:
        result = subprocess.run(
            [sys.executable, '-S', '-m', 'examples.telegram_peers'], cwd=ROOT,
            env={'PATH': os.defpath}, capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn('--env-file', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_help_needs_neither_credentials_nor_third_party_imports(self) -> None:
        result = subprocess.run(
            [sys.executable, '-S', '-m', 'examples.telegram_peers', '--help'],
            cwd=ROOT,
            env={'PATH': os.defpath, 'PYTHONIOENCODING': 'utf-8'},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ('--env-file', '--peer', '--peer-name', '--peer-description', '--instructions', '--multimodal'):
            self.assertIn(flag, result.stdout)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
