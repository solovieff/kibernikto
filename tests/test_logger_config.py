"""Offline regressions for logging wiring: one formatted console line per record, everything exported to Logfire."""

import io
import logging
import unittest
from unittest.mock import MagicMock, patch

import logfire
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from kibernikto import config


class _RootSnapshot:
    """Restore root/project logger state so tests never leak handlers into the rest of the suite."""

    def __enter__(self) -> None:
        root = logging.getLogger()
        self._root = (root.level, list(root.handlers))
        self._levels = {name: logging.getLogger(name).level for name in config.LOGGER_LEVELS}

    def __exit__(self, *exc: object) -> None:
        root = logging.getLogger()
        for handler in root.handlers:
            if handler not in self._root[1]:
                handler.close()
        root.setLevel(self._root[0])
        root.handlers[:] = self._root[1]
        for name, level in self._levels.items():
            logging.getLogger(name).setLevel(level)


class ConfigureLoggerWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        snapshot = _RootSnapshot()
        snapshot.__enter__()
        self.addCleanup(snapshot.__exit__, None, None, None)
        self.factory = MagicMock(name='LogfireLoggingHandler', return_value=logging.NullHandler())
        with patch.object(config.logfire, 'configure') as self.configure, \
                patch.object(config.logfire, 'instrument_pydantic_ai') as self.instrument, \
                patch.object(config.logfire, 'LogfireLoggingHandler', self.factory):
            config.configure_logger()
            config.configure_logger()  # idempotency

    def test_logfire_console_stays_env_driven_for_spans(self) -> None:
        kwargs = self.configure.call_args.kwargs
        self.assertNotIn('console', kwargs)
        self.assertEqual(kwargs['send_to_logfire'], 'if-token-present')
        self.instrument.assert_called()

    def test_root_has_exactly_console_and_logfire_handlers(self) -> None:
        handlers = logging.getLogger().handlers
        self.assertEqual(len(handlers), 2)
        self.assertIn(self.factory.return_value, handlers)
        stream = next(h for h in handlers if type(h) is logging.StreamHandler)
        self.assertEqual(stream.formatter._fmt, config.LOG_FORMAT)
        self.assertEqual(logging.getLogger().level, logging.WARN)

    def test_logfire_handler_does_not_print_records_twice(self) -> None:
        kwargs = self.factory.call_args.kwargs
        self.assertIsInstance(kwargs['fallback'], logging.NullHandler)
        self.assertFalse(kwargs['logfire_instance']._console_log)

    def test_project_logger_levels(self) -> None:
        for name, level in config.LOGGER_LEVELS.items():
            self.assertEqual(logging.getLogger(name).level, level)
            self.assertEqual(logging.getLogger(name).handlers, [])


class ConfigureLoggerExportTests(unittest.TestCase):
    """Real Logfire SDK with an in-memory exporter: what is exported vs printed."""

    def setUp(self) -> None:
        snapshot = _RootSnapshot()
        snapshot.__enter__()
        self.addCleanup(snapshot.__exit__, None, None, None)
        self.exporter = InMemorySpanExporter()
        real_configure = logfire.configure

        def configure_in_memory(**kwargs: object) -> None:
            real_configure(send_to_logfire=False, console=False, service_name=str(kwargs['service_name']),
                           additional_span_processors=[SimpleSpanProcessor(self.exporter)], metrics=False)

        self.stderr = io.StringIO()
        with patch.object(config.logfire, 'configure', configure_in_memory), \
                patch.object(config.logfire, 'instrument_pydantic_ai'), \
                patch('sys.stderr', self.stderr):
            config.configure_logger()
            logging.getLogger('kibernikto.probe').debug('kib-debug')
            logging.getLogger('thirdparty.probe').warning('third-warn')
            logging.getLogger('thirdparty.probe').info('third-info')

    def _exported(self) -> list[str]:
        return [span.attributes.get('logfire.msg') for span in self.exporter.get_finished_spans()]

    def test_project_and_third_party_warnings_are_exported(self) -> None:
        exported = self._exported()
        self.assertIn('kib-debug', exported)
        self.assertIn('third-warn', exported)
        self.assertNotIn('third-info', exported)

    def test_each_record_is_printed_once_in_project_format(self) -> None:
        lines = self.stderr.getvalue().splitlines()
        self.assertEqual(sum('kib-debug' in line for line in lines), 1)
        self.assertEqual(sum('third-warn' in line for line in lines), 1)
        self.assertTrue(any(line.startswith('DEBUG') and 'kibernikto.probe:' in line for line in lines))


if __name__ == '__main__':
    unittest.main()
