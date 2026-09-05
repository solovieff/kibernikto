"""Guard package discovery: a successful wheel build must include subpackages."""
import tomllib
import unittest
from pathlib import Path


class DistributionTests(unittest.TestCase):
    def test_subpackages_are_discovered_and_nonlibrary_dirs_excluded(self):
        root = Path(__file__).resolve().parents[1]
        config = tomllib.loads((root / 'pyproject.toml').read_text())
        packages = config['tool']['setuptools']['packages']
        self.assertIsInstance(packages, dict, 'A root-only package list drops all subpackages from wheels')
        self.assertEqual(packages['find']['include'], ['kibernikto*'])
        self.assertFalse(packages['find']['namespaces'])
