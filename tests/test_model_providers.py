"""Offline regressions: provider-prefixed model strings resolve via the OpenAI-compatible registry."""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel

from kibernikto.ai.agent import utils
from kibernikto.ai.agent.core import image
from kibernikto.ai.agent.utils import (
    OPENAI_COMPATIBLE_PROVIDERS, KiberniktoOpenAIProvider, MissingProviderKeyError,
    infer_kibernikto_model, register_openai_compatible,
)

_KEYS = {'VSEGPT_API_KEY': 'k-vse', 'ROUTERAI_API_KEY': 'k-router', 'BEGET_AI_API_KEY': 'k-beget'}


class OpenAICompatibleRegistryTest(unittest.TestCase):
    def test_every_registered_prefix_builds_openai_chat_model(self) -> None:
        with patch.dict(os.environ, _KEYS):
            for prefix, spec in OPENAI_COMPATIBLE_PROVIDERS.items():
                with self.subTest(prefix=prefix):
                    model = infer_kibernikto_model(f'{prefix}:vendor/some-model')
                    self.assertIsInstance(model, OpenAIChatModel)
                    self.assertEqual(model.model_name, 'vendor/some-model')
                    self.assertEqual(model._provider.name, prefix)
                    self.assertEqual(str(model._provider.client.base_url).rstrip('/'), spec.base_url.rstrip('/'))

    def test_beget_uses_its_url_and_key(self) -> None:
        with patch.dict(os.environ, _KEYS):
            provider = infer_kibernikto_model('beget:some-model')._provider
        self.assertEqual(str(provider.client.base_url), 'https://api-llm.beget.com/v1/')
        self.assertEqual(provider.client.api_key, 'k-beget')
        self.assertEqual(provider.image_api, 'images')

    def test_missing_key_names_the_env_var(self) -> None:
        with patch.dict(os.environ, {'BEGET_AI_API_KEY': ''}):
            with self.assertRaisesRegex(MissingProviderKeyError, 'BEGET_AI_API_KEY'):
                infer_kibernikto_model('beget:some-model')

    def test_runtime_registration(self) -> None:
        try:
            register_openai_compatible('acme', 'https://llm.acme.test/v1', 'ACME_KEY', image_api='chat')
            with patch.dict(os.environ, {'ACME_KEY': 'k-acme'}):
                provider = infer_kibernikto_model('acme:m')._provider
            self.assertIsInstance(provider, KiberniktoOpenAIProvider)
            self.assertEqual(provider.image_api, 'chat')
            self.assertIn('acme', utils.known_prefixes())
        finally:
            OPENAI_COMPATIBLE_PROVIDERS.pop('acme', None)

    def test_openrouter_and_fallthrough_untouched(self) -> None:
        self.assertIsInstance(infer_kibernikto_model('openrouter:x/y'), OpenRouterModel)
        self.assertIsNone(infer_kibernikto_model(None))
        with self.assertRaisesRegex(ValueError, 'beget'):
            infer_kibernikto_model('no-prefix')


class ImageRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def _route(self, model_name: str) -> str:
        with patch.dict(os.environ, _KEYS):
            agent = MagicMock(model=infer_kibernikto_model(model_name))
        ctx = MagicMock()
        ctx.deps.user_message_parts = []
        with patch.object(image, '_get_image_agent', return_value=agent), \
             patch.object(image, '_openrouter_generate_images', AsyncMock(return_value=[])) as chat, \
             patch.object(image, '_images_generate', AsyncMock(return_value=[])) as classic:
            await image.generate_image(ctx, 'a cat')
        return 'chat' if chat.await_count else 'images' if classic.await_count else 'none'

    async def test_image_api_follows_registry(self) -> None:
        self.assertEqual(await self._route('routerai:img'), 'chat')
        self.assertEqual(await self._route('vsegpt:img'), 'images')
        self.assertEqual(await self._route('beget:img'), 'images')


if __name__ == '__main__':
    unittest.main()
