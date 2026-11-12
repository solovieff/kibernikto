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
