"""Offline tests for ConversationHistory capability: loading, ProcessHistory sanitization, and saving."""

import os
import unittest

os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from pydantic_ai import Agent, ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.messages import BinaryContent, BinaryImage, FilePart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.ai.agent.harness.conversation_history import ConversationHistory
from kibernikto.storage.base import MemoryHistoryStorage


class ConversationHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.storage = MemoryHistoryStorage(history_size=10)

    async def test_loads_history_before_run_and_saves_new_messages_after_run(self) -> None:
        from kibernikto.ai.agent.harness.conversation_history import ConversationHistory

        # Seed initial history in storage
        await self.storage.add_messages('chat-1', [
            ModelRequest(parts=[UserPromptPart(content='hello')]),
            ModelResponse(parts=[TextPart(content='hi there')]),
        ])

        seen_messages: list[list[ModelMessage]] = []

        def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen_messages.append(list(messages))
            return ModelResponse(parts=[TextPart(content='doing great')])

        agent = Agent(
            FunctionModel(model_fn),
            deps_type=KiberniktoDeps,
            capabilities=[ConversationHistory(storage=self.storage, history_size=6)],
        )

        res = await agent.run('how are you?', conversation_id='chat-1', deps=KiberniktoDeps())
        self.assertEqual(res.output, 'doing great')

        # Model should have seen prior conversation (2 messages) + new prompt (1 message) = 3
        self.assertEqual(len(seen_messages), 1)
        self.assertEqual(len(seen_messages[0]), 3)

        # Storage should now contain prior 2 + new 2 = 4 messages
        saved = await self.storage.get_conversation('chat-1')
        self.assertEqual(len(saved), 4)

    async def test_process_history_windows_and_sanitizes(self) -> None:
        from kibernikto.ai.agent.harness.conversation_history import ConversationHistory
        from pydantic_ai.messages import ThinkingPart

        # Seed 6 messages
        initial = []
        for i in range(3):
            initial.extend([
                ModelRequest(parts=[UserPromptPart(content=f'q{i}')]),
                ModelResponse(parts=[ThinkingPart(content=f'think{i}'), TextPart(content=f'a{i}')]),
            ])
        await self.storage.add_messages('chat-2', initial)

        seen_messages: list[list[ModelMessage]] = []

        def model_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen_messages.append(list(messages))
            return ModelResponse(parts=[TextPart(content='done')])

        # Window size = 2 (1 request-response pair) + keep_thinking = False
        agent = Agent(
            FunctionModel(model_fn),
            deps_type=KiberniktoDeps,
            capabilities=[ConversationHistory(storage=self.storage, history_size=2, keep_thinking=False)],
        )

        await agent.run('q_final', conversation_id='chat-2', deps=KiberniktoDeps())
        self.assertEqual(len(seen_messages), 1)
        # Should be windowed: only the last request/response plus the new prompt
        # And thinking parts must be stripped
        for msg in seen_messages[0]:
            if isinstance(msg, ModelResponse):
                self.assertFalse(any(isinstance(p, ThinkingPart) for p in msg.parts))

    def test_history_storage_of_finds_storage_or_none(self) -> None:
        from kibernikto.ai.agent.harness.conversation_history import ConversationHistory, history_storage_of
        with_history = Agent(FunctionModel(lambda m, i: ModelResponse(parts=[TextPart('x')])),
                             capabilities=[ConversationHistory(storage=self.storage)])
        bare = Agent(FunctionModel(lambda m, i: ModelResponse(parts=[TextPart('x')])))
        self.assertIs(history_storage_of(with_history), self.storage)
        self.assertIsNone(history_storage_of(bare))


class MaterializeAttachmentsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.result = await Agent(TestModel(custom_output_text='done')).run('hello')

    async def test_image_is_narrowed_and_metadata_is_preserved(self) -> None:
        image = BinaryContent(data=b'image', media_type='image/png', identifier='generated-image',
                              vendor_metadata={'filename': 'image.png'})
        deps = KiberniktoDeps(attachments=[image])

        ConversationHistory._materialize_attachments(self.result, deps)

        content = self.result.response.files[0]
        self.assertIsInstance(content, BinaryImage)
        self.assertEqual(content.data, image.data)
        self.assertEqual(content.identifier, image.identifier)
        self.assertEqual(content.vendor_metadata, image.vendor_metadata)

    async def test_audio_and_document_remain_non_image_files(self) -> None:
        attachments = [
            BinaryContent(data=b'audio', media_type='audio/mpeg'),
            BinaryContent(data=b'pdf', media_type='application/pdf'),
        ]

        ConversationHistory._materialize_attachments(self.result, KiberniktoDeps(attachments=attachments))

        self.assertEqual(self.result.response.files, attachments)
        self.assertTrue(all(not isinstance(content, BinaryImage) for content in self.result.response.files))

    async def test_existing_files_and_repeated_attachments_are_not_duplicated(self) -> None:
        existing = BinaryImage(data=b'existing', media_type='image/png')
        added = BinaryImage(data=b'added', media_type='image/jpeg')
        self.result.response.parts.append(FilePart(content=existing))
        deps = KiberniktoDeps(attachments=[existing, added, added])

        ConversationHistory._materialize_attachments(self.result, deps)
        ConversationHistory._materialize_attachments(self.result, deps)

        self.assertEqual([content.data for content in self.result.response.files], [b'existing', b'added'])


if __name__ == '__main__':
    unittest.main()
