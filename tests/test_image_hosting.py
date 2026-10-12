"""Offline regressions for public image hosting: provider selection, S3 keys/URLs/headers, imgbb guards."""

import os
import re
import unittest
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'

from botocore.exceptions import ClientError
from pydantic import ValidationError

from kibernikto.storage.config import STORAGE_SETTINGS
from kibernikto.utils import image_hosting as hosting

_PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16
_JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 16
_WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 '

_S3_ENV = {
    'IMAGE_HOSTING_PROVIDER': 's3',
    'IMAGE_S3_PUBLIC_BASE_URL': 'https://cdn.example.com/media/',
    'IMAGE_S3_BUCKET': 'public-bucket',
}


def _settings(env: dict[str, str]) -> hosting.ImageHostingSettings:
    with patch.dict(os.environ, env, clear=False):
        return hosting.ImageHostingSettings()


def _with_s3_credentials():  # noqa: ANN202 — patch context manager
    return patch.multiple(STORAGE_SETTINGS, S3_ACCESS_KEY='ak', S3_SECRET_KEY='sk', S3_ENDPOINT='https://s3.test')


class ContentTypeTests(unittest.TestCase):
    def test_magic_bytes_win_over_name(self) -> None:
        self.assertEqual(hosting.sniff_content_type(_PNG, 'x.jpg'), 'image/png')
        self.assertEqual(hosting.sniff_content_type(_JPEG, 'x'), 'image/jpeg')
        self.assertEqual(hosting.sniff_content_type(_WEBP, 'x'), 'image/webp')
        self.assertEqual(hosting.sniff_content_type(b'GIF89a...', 'x'), 'image/gif')

    def test_name_then_generic_fallback(self) -> None:
        self.assertEqual(hosting.sniff_content_type(b'??', 'photo.webp'), 'image/webp')
        self.assertEqual(hosting.sniff_content_type(b'??', 'AgADBQAD'), 'application/octet-stream')


class SettingsTests(unittest.TestCase):
    def test_default_is_imgbb(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = hosting.ImageHostingSettings()
        self.assertEqual(settings.HOSTING_PROVIDER, 'imgbb')
        self.assertIsInstance(hosting.get_image_hosting(settings), hosting.ImgbbImageHosting)

    def test_existing_env_names_are_kept(self) -> None:
        settings = _settings({'IMAGE_STORAGE_API_KEY': 'k', 'IMAGE_STORAGE_EXPIRATION': '60'})
        self.assertEqual((settings.STORAGE_API_KEY, settings.STORAGE_EXPIRATION), ('k', 60))

    def test_unknown_provider_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            _settings({'IMAGE_HOSTING_PROVIDER': 'dropbox'})

    def test_s3_requires_public_url_and_credentials(self) -> None:
        with patch.multiple(STORAGE_SETTINGS, S3_ACCESS_KEY=None, S3_SECRET_KEY=None):
            with self.assertRaisesRegex(ValidationError, 'APP_STORAGE_S3_ACCESS_KEY'):
                _settings(_S3_ENV)
        with _with_s3_credentials(), self.assertRaisesRegex(ValidationError, 'IMAGE_S3_PUBLIC_BASE_URL'):
            _settings({**_S3_ENV, 'IMAGE_S3_PUBLIC_BASE_URL': ''})
        with _with_s3_credentials(), self.assertRaisesRegex(ValidationError, 'absolute'):
            _settings({**_S3_ENV, 'IMAGE_S3_PUBLIC_BASE_URL': 'cdn.example.com'})

    def test_s3_bucket_falls_back_to_storage_bucket(self) -> None:
        with _with_s3_credentials(), patch.object(STORAGE_SETTINGS, 'S3_BUCKET', 'storage-bucket'):
            settings = _settings({**_S3_ENV, 'IMAGE_S3_BUCKET': ''})
            self.assertEqual(settings.s3_bucket, 'storage-bucket')
            self.assertIsInstance(hosting.get_image_hosting(settings), hosting.S3ImageHosting)


class S3ImageHostingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        with _with_s3_credentials():
            self.settings = _settings(_S3_ENV)
        self.provider = hosting.S3ImageHosting(self.settings)
        self.client = AsyncMock()
        self.provider._client = self.client

    async def test_publish_uploads_immutable_typed_object_and_returns_public_url(self) -> None:
        url = await self.provider.publish(_PNG, 'AgADBQAD')
        kwargs = self.client.put_object.await_args.kwargs
        self.assertEqual(kwargs['Bucket'], 'public-bucket')
        self.assertRegex(kwargs['Key'], r'^public/\d{4}/\d{2}/[0-9a-f]{32}\.png$')
        self.assertEqual(kwargs['ContentType'], 'image/png')
        self.assertIn('immutable', kwargs['CacheControl'])
        self.assertNotIn('ACL', kwargs)
        self.assertEqual(url, f"https://cdn.example.com/media/{kwargs['Key']}")

    async def test_keys_are_unique_and_jpeg_uses_jpg(self) -> None:
        first = await self.provider.publish(_JPEG, 'a')
        second = await self.provider.publish(_JPEG, 'a')
        self.assertNotEqual(first, second)
        self.assertTrue(first.endswith('.jpg'))

    async def test_optional_acl_and_empty_prefix(self) -> None:
        with _with_s3_credentials():
            settings = _settings({**_S3_ENV, 'IMAGE_S3_ACL': 'public-read', 'IMAGE_S3_PREFIX': '/'})
        provider = hosting.S3ImageHosting(settings)
        provider._client = self.client
        url = await provider.publish(_PNG, 'x')
        self.assertEqual(self.client.put_object.await_args.kwargs['ACL'], 'public-read')
        self.assertTrue(re.match(r'^https://cdn\.example\.com/media/\d{4}/\d{2}/[0-9a-f]{32}\.png$', url), url)

    async def test_upload_error_returns_none(self) -> None:
        self.client.put_object.side_effect = ClientError({'Error': {'Code': 'AccessDenied'}}, 'PutObject')
        with self.assertLogs('kibernikto.utils.image_hosting', 'ERROR'):
            self.assertIsNone(await self.provider.publish(_PNG, 'x'))

    async def test_aclose_releases_client_once(self) -> None:
        await self.provider.aclose()
        await self.provider.aclose()
        self.client.__aexit__.assert_awaited_once_with(None, None, None)
        self.assertIsNone(self.provider._client)


class ImgbbImageHostingTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_skips_network(self) -> None:
        provider = hosting.ImgbbImageHosting(_settings({'IMAGE_STORAGE_API_KEY': ''}))
        with patch.object(hosting.aiohttp, 'ClientSession') as session, \
                self.assertLogs('kibernikto.utils.image_hosting', 'ERROR'):
            self.assertIsNone(await provider.publish(_PNG, 'x'))
        session.assert_not_called()


class ValidationTests(unittest.TestCase):
    def test_s3_provider_heads_public_bucket(self) -> None:
        with _with_s3_credentials():
            settings = _settings(_S3_ENV)
        with patch('kibernikto.storage.config.check_s3_bucket') as check:
            hosting.validate_image_hosting(settings)
        check.assert_called_once_with('public-bucket')

    def test_imgbb_without_key_warns_without_network(self) -> None:
        with self.assertLogs('kibernikto.utils.image_hosting', 'WARNING'):
            hosting.validate_image_hosting(_settings({'IMAGE_STORAGE_API_KEY': ''}))

    def test_validate_storage_includes_image_hosting(self) -> None:
        from kibernikto.storage.config import validate_storage
        with patch.object(hosting, 'validate_image_hosting') as check:
            validate_storage()
        check.assert_called_once_with()


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_shutdown_closes_image_hosting(self) -> None:
        from kibernikto.telegram.agent.telegram_app import TelegramApp
        from kibernikto.telegram.config import TELEGRAM_SETTINGS
        from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent
        from pydantic_ai.models.test import TestModel

        from aiogram import Dispatcher

        # Module-level routers attach to one Dispatcher per process; this test only needs the hooks.
        with patch.object(TELEGRAM_SETTINGS, 'BOT_KEY', '100:offline-test-token'), \
                patch.object(Dispatcher, 'include_router'):
            app = TelegramApp.from_agent(TelegramAgent(model=TestModel()))
        self.addAsyncCleanup(app.bot.session.close)
        with patch.object(hosting.image_hosting, 'aclose', AsyncMock()) as aclose, \
                patch('kibernikto.storage.factory.shutdown_storage', AsyncMock()):
            await app.dispatcher.emit_shutdown(bot=app.bot)
        aclose.assert_awaited_once_with()


if __name__ == '__main__':
    unittest.main()

