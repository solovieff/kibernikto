"""Offline regressions for group reaction calls; substring matching is intentional."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot
from aiogram.types import Chat, Message, User, Voice

from kibernikto.ai.agent.telegram.identity import BotIdentity
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.handlers import conversation
from kibernikto.telegram.utils.permissions import should_react


def group_message(
    text: str | None = None,
    *,
    caption: str | None = None,
    reply_author: User | None = None,
    voice: Voice | None = None,
) -> Message:
    bot = AsyncMock(spec=Bot)
    bot.id = 1001
    chat = Chat(id=-3003, type='supergroup', title='Test group')
    date = datetime.now(timezone.utc)
    replied = Message(message_id=1, date=date, chat=chat, from_user=reply_author, text='Previous message') \
        if reply_author is not None else None
    return Message(
        message_id=2, date=date, chat=chat,
        from_user=User(id=2002, is_bot=False, first_name='User'),
        text=text, caption=caption, reply_to_message=replied, voice=voice,
    ).as_(bot)


class ReactionCallsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.object(TELEGRAM_SETTINGS, 'REACTION_CALLS', ['Киберникто', 'swarm host']))
        self.identity = self.enterContext(patch(
            'kibernikto.ai.agent.telegram.identity.get_bot_identity',
            return_value=BotIdentity(full_name='Test Assistant', username='test_assistant_bot'),
        ))

    def test_configured_calls_match_case_insensitively(self) -> None:
        for text in ('Эй, КИБЕРНИКТО!', 'киберникто, помоги', 'Hello, SWARM HOST!'):
            with self.subTest(text=text):
                self.assertTrue(should_react(group_message(text)))

    def test_substring_matching_is_preserved(self) -> None:
        self.assertTrue(should_react(group_message('киберниктошка')))
        with patch.object(TELEGRAM_SETTINGS, 'REACTION_CALLS', ['hi']):
            self.assertTrue(should_react(group_message('this is a test')))

    def test_caption_can_trigger_reaction(self) -> None:
        self.assertTrue(should_react(group_message(caption='КИБЕРНИКТО, что на фото?')))
        self.assertFalse(should_react(group_message(caption='Просто фото')))

    def test_bot_name_and_username_work_without_configured_calls(self) -> None:
        with patch.object(TELEGRAM_SETTINGS, 'REACTION_CALLS', []):
            for text in ('Hello, TEST ASSISTANT!', '@TEST_ASSISTANT_BOT, help'):
                with self.subTest(text=text):
                    self.assertTrue(should_react(group_message(text)))

    def test_unrelated_text_is_ignored(self) -> None:
        self.assertFalse(should_react(group_message('Разговариваем между собой')))

    def test_reply_to_this_bot_needs_no_call(self) -> None:
        author = User(id=1001, is_bot=True, first_name='Test Assistant')
        self.assertTrue(should_react(group_message('Продолжай', reply_author=author)))

    def test_reply_to_someone_else_does_not_trigger_reaction(self) -> None:
        for is_bot in (False, True):
            with self.subTest(is_bot=is_bot):
                author = User(id=9009, is_bot=is_bot, first_name='Other')
                self.assertFalse(should_react(group_message('Продолжай', reply_author=author)))

    def test_call_still_works_in_reply_to_someone_else(self) -> None:
        author = User(id=9009, is_bot=False, first_name='Other')
        self.assertTrue(should_react(group_message('Киберникто, а ты что думаешь?', reply_author=author)))

    def test_calls_work_before_bot_identity_is_loaded(self) -> None:
        self.identity.return_value = None
        self.assertTrue(should_react(group_message('Киберникто!')))
        self.assertFalse(should_react(group_message('Постороннее сообщение')))

    def test_no_calls_and_no_identity_do_not_match_everything(self) -> None:
        self.identity.return_value = BotIdentity()
        with patch.object(TELEGRAM_SETTINGS, 'REACTION_CALLS', []):
            self.assertFalse(should_react(group_message('Постороннее сообщение')))

    def test_empty_text_is_ignored(self) -> None:
        for text in (None, ''):
            with self.subTest(text=text):
                self.assertFalse(should_react(group_message(text)))

    def test_voice_without_text_triggers_reaction_in_reply_to_bot(self) -> None:
        author = User(id=1001, is_bot=True, first_name='Test Assistant')
        voice = Voice(file_id='voice', file_unique_id='voice-unique', duration=1)
        self.assertTrue(should_react(group_message(reply_author=author, voice=voice)))

    def test_reply_to_bot_needs_neither_text_nor_loaded_identity(self) -> None:
        author = User(id=1001, is_bot=True, first_name='Test Assistant')
        self.identity.return_value = None
        with patch.object(TELEGRAM_SETTINGS, 'REACTION_CALLS', []):
            self.assertTrue(should_react(group_message(reply_author=author)))

    def test_voice_without_text_is_ignored_unless_reply_is_to_this_bot(self) -> None:
        voice = Voice(file_id='voice', file_unique_id='voice-unique', duration=1)
        for author in (None, User(id=9009, is_bot=True, first_name='Other')):
            with self.subTest(author=author):
                self.assertFalse(should_react(group_message(reply_author=author, voice=voice)))

    def test_reply_with_missing_author_is_not_treated_as_reply_to_bot(self) -> None:
        author = User(id=9009, is_bot=False, first_name='Other')
        message = group_message(reply_author=author)
        replied = message.reply_to_message.model_copy(update={'from_user': None})
        message = message.model_copy(update={'reply_to_message': replied})
        self.assertFalse(should_react(message))


class GroupReactionHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_passes_voice_reply_without_text_to_processing(self) -> None:
        author = User(id=1001, is_bot=True, first_name='Test Assistant')
        voice = Voice(file_id='voice', file_unique_id='voice-unique', duration=1)
        message = group_message(reply_author=author, voice=voice)
        with patch.object(conversation, '_process_and_reply', new_callable=AsyncMock) as process:
            await conversation.conversation_router.propagate_event('message', message, bot=message.bot)
            process.assert_awaited_once_with(message)

    async def test_handler_only_processes_messages_that_trigger_reaction(self) -> None:
        with patch.object(TELEGRAM_SETTINGS, 'REACTION_CALLS', ['киберникто']), \
                patch('kibernikto.ai.agent.telegram.identity.get_bot_identity', return_value=None), \
                patch.object(conversation, '_process_and_reply', new_callable=AsyncMock) as process:
            await conversation.handle_group_message(group_message('Постороннее сообщение'))
            process.assert_not_awaited()
            message = group_message('КИБЕРНИКТО, привет!')
            await conversation.handle_group_message(message)
            process.assert_awaited_once_with(message)