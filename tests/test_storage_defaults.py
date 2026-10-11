"""Offline regressions for durable SQLite defaults and SQL path resolution."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kibernikto.storage.config import StorageSettings
from kibernikto.storage.sql import engine


class SqliteDefaultTests(unittest.TestCase):
    def test_default_sqlite_path_is_durable_file(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(StorageSettings().SQLITE_PATH, '~/.kibernikto/kibernikto.db')

    def test_memory_path_is_kept_without_directories(self) -> None:
        self.assertEqual(engine._sqlite_file(':memory:'), ':memory:')

    def test_parent_directory_is_created_and_user_home_expanded(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}):
            path = engine._sqlite_file('~/nested/bot.db')
            self.assertEqual(Path(path), Path(home) / 'nested' / 'bot.db')
            self.assertTrue((Path(home) / 'nested').is_dir())


if __name__ == '__main__':
    unittest.main()