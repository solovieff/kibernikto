"""Offline regressions: provider-prefixed model strings resolve via the OpenAI-compatible registry."""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import ModelSettings
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel

from kibernikto.ai.agent import utils
from kibernikto.ai.agent.core import image
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.config import APP_SETTINGS
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


class AttributionHeadersTest(unittest.IsolatedAsyncioTestCase):
    async def _sent_headers(self, **kwargs) -> dict[str, str]:
        seen: dict[str, str] = {}

        def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen.update((info.model_settings or {}).get('extra_headers', {}))
            return ModelResponse(parts=[TextPart('ok')])

        agent = KiberniktoAgent(model=FunctionModel(reply), persona=False, history_storage=None, **kwargs)
        await agent.run('hi')
        return seen

    async def test_agent_name_labels_every_request(self) -> None:
        headers = await self._sent_headers(name='expert', model_settings=ModelSettings(temperature=0.1))
        self.assertEqual(headers, {'X-Title': f'{APP_SETTINGS.INSTANCE_NAME}:expert',
                                   'HTTP-Referer': APP_SETTINGS.URL})

    async def test_explicit_headers_win(self) -> None:
        headers = await self._sent_headers(name='expert',
                                           model_settings=ModelSettings(extra_headers={'X-Title': 'mine'}))
        self.assertEqual(headers['X-Title'], 'mine')
        self.assertEqual(headers['HTTP-Referer'], APP_SETTINGS.URL)

    async def test_raw_image_calls_carry_headers(self) -> None:
        create = AsyncMock(return_value=MagicMock(data=[]))
        model = MagicMock(model_name='img')
        model._provider.client.images.generate = create
        agent = MagicMock(model=model, model_settings=utils.with_attribution(None, image.IMAGE_ENGINE_NAME))
        with patch.object(image, '_get_image_agent', return_value=agent):
            await image._images_generate('a cat')
        self.assertEqual(create.await_args.kwargs['extra_headers']['X-Title'],
                         f'{APP_SETTINGS.INSTANCE_NAME}:{image.IMAGE_ENGINE_NAME}')


if __name__ == '__main__':
    unittest.main()
