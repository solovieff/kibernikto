"""Offline regressions for history image link checks: dead links become text, live ones are stored once."""

import os
import unittest
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai.messages import ImageUrl, ModelRequest, TextPart, ModelResponse, UserPromptPart

from kibernikto.ai.agent.core.media_check import DEAD_LINK_TEXT, check_history_images



def _image_turn(image: ImageUrl) -> list:
    return [ModelRequest(parts=[UserPromptPart(content=['look', image])]),
            ModelResponse(parts=[TextPart(content='ok')])]


def _request_content(messages: list) -> list:
    return messages[0].parts[0].content


class CheckHistoryImagesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.exists = AsyncMock(return_value=False)
        self.save = AsyncMock()
        self.head = AsyncMock(return_value=True)
        self.fetch = AsyncMock(return_value=b'bytes')

    async def _run(self, messages: list) -> tuple[list, bool]:
        return await check_history_images(messages, conversation_id='1', exists=self.exists, save=self.save,
                                          head=self.head, fetch=self.fetch)

    async def test_dead_link_is_replaced_with_text(self) -> None:
        self.head.return_value = False
        messages = _image_turn(ImageUrl(url='https://i.ibb.co/dead.jpg'))
        fixed, changed = await self._run(messages)
        self.assertTrue(changed)
        self.assertEqual(_request_content(fixed)[1], DEAD_LINK_TEXT)
        self.save.assert_not_awaited()

    async def test_live_link_without_stored_copy_is_fetched_and_saved_once(self) -> None:
        image = ImageUrl(url='https://i.ibb.co/live.jpg', vendor_metadata={'media_ref': '7/a.jpg', 'media_store': 'telegram'})
        fixed, changed = await self._run(_image_turn(image))
        self.assertFalse(changed)
        self.assertIsInstance(_request_content(fixed)[1], ImageUrl)
        self.fetch.assert_awaited_once_with('https://i.ibb.co/live.jpg')
        self.save.assert_awaited_once_with('telegram', '7/a.jpg', b'bytes')

    async def test_stored_copy_skips_download_but_head_still_runs(self) -> None:
        self.exists.return_value = True
        image = ImageUrl(url='https://i.ibb.co/live.jpg', vendor_metadata={'media_ref': '7/a.jpg', 'media_store': 'telegram'})
        await self._run(_image_turn(image))
        self.head.assert_awaited_once_with('https://i.ibb.co/live.jpg')
        self.exists.assert_awaited_once_with('telegram', '7/a.jpg')
        self.fetch.assert_not_awaited()
        self.save.assert_not_awaited()

    async def test_stored_copy_does_not_hide_dead_link(self) -> None:
        self.exists.return_value = True
        self.head.return_value = False
        image = ImageUrl(url='https://i.ibb.co/dead.jpg', vendor_metadata={'media_ref': '7/a.jpg', 'media_store': 'telegram'})
        fixed, changed = await self._run(_image_turn(image))
        self.assertTrue(changed)
        self.assertEqual(_request_content(fixed)[1], DEAD_LINK_TEXT)
        self.fetch.assert_not_awaited()

    async def test_link_without_media_ref_is_only_checked_not_stored(self) -> None:
        fixed, changed = await self._run(_image_turn(ImageUrl(url='https://i.ibb.co/old.jpg')))
        self.assertFalse(changed)
        self.head.assert_awaited_once_with('https://i.ibb.co/old.jpg')
        self.save.assert_not_awaited()
        self.assertIsInstance(_request_content(fixed)[1], ImageUrl)

    async def test_history_without_images_is_untouched(self) -> None:
        messages = [ModelRequest(parts=[UserPromptPart(content='hi')])]
        fixed, changed = await self._run(messages)
        self.assertFalse(changed)
        self.head.assert_not_awaited()
        self.assertEqual(fixed[0].parts[0].content, 'hi')


class AgentRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_dead_history_link_reaches_model_as_text_and_history_is_rewritten(self) -> None:
        from pydantic_ai.models.function import AgentInfo, FunctionModel
        from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
        from kibernikto.storage.base import MemoryHistoryStorage

        seen: list = []

        def model(messages, info: AgentInfo) -> ModelResponse:
            seen.append(messages)
            return ModelResponse(parts=[TextPart(content='done')])

        storage = MemoryHistoryStorage(history_size=10)
        dead = ImageUrl(url='https://i.ibb.co/dead.jpg')
        await storage.add_messages('4', _image_turn(dead))
        agent = KiberniktoAgent(model=FunctionModel(model), history_storage=storage)

        # Offline: the probes in conversation_history are replaced, so aiohttp is never reached.
        with patch('kibernikto.ai.agent.harness.conversation_history.head_alive', AsyncMock(return_value=False)), \
             patch('kibernikto.ai.agent.harness.conversation_history.fetch_bytes', AsyncMock(return_value=b'')), \
             patch('kibernikto.ai.agent.harness.conversation_history.check_history_images', wraps=check_history_images) as wrapped:
            await agent.run('next', conversation_id='4')

        sent = seen[0]
        sent_contents = [part.content for msg in sent for part in msg.parts if isinstance(part, UserPromptPart)]
        flat = [item for content in sent_contents if isinstance(content, list) for item in content]
        self.assertNotIn(dead, [item for item in flat if isinstance(item, ImageUrl)])
        self.assertIn(DEAD_LINK_TEXT, flat)
        self.assertTrue(wrapped.called)
        stored = await storage.get_full_conversation('4')
        stored_items = [i for m in stored if isinstance(m, ModelRequest) for p in m.parts
                        if isinstance(p, UserPromptPart) and isinstance(p.content, list) for i in p.content]
        self.assertNotIn(dead, stored_items)
        self.assertIn(DEAD_LINK_TEXT, stored_items)

    async def test_repairing_dead_link_in_window_preserves_older_history(self) -> None:
        from pydantic_ai.models.function import AgentInfo, FunctionModel
        from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
        from kibernikto.storage.base import MemoryHistoryStorage

        def model(messages, info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content='done')])

        storage = MemoryHistoryStorage(history_size=2)
        await storage.add_messages('4', [
            ModelRequest(parts=[UserPromptPart(content='ancient fact before window')]),
            ModelResponse(parts=[TextPart(content='noted')]),
        ])
        dead = ImageUrl(url='https://i.ibb.co/dead.jpg')
        await storage.add_messages('4', _image_turn(dead))

        agent = KiberniktoAgent(model=FunctionModel(model), history_storage=storage)
        with patch('kibernikto.ai.agent.harness.conversation_history.head_alive', AsyncMock(return_value=False)), \
             patch('kibernikto.ai.agent.harness.conversation_history.fetch_bytes', AsyncMock(return_value=b'')):
            await agent.run('next', conversation_id='4')

        full = await storage.get_full_conversation('4')
        self.assertEqual(full[0].parts[0].content, 'ancient fact before window')
        self.assertEqual(full[1].parts[0].content, 'noted')
        self.assertEqual(full[2].parts[0].content, ['look', DEAD_LINK_TEXT])


if __name__ == '__main__':
    unittest.main()
