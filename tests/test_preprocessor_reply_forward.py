"""Offline coverage for reply, quote, external reply and forward context in the Telegram preprocessor."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['AGENT_KIBERNIKTO_IMAGE_MODEL_NAME'] = ''
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot
from aiogram.types import (
    Chat, ExternalReplyInfo, Message, MessageOriginChannel, MessageOriginChat, MessageOriginHiddenUser,
    MessageOriginUser, PhotoSize, Sticker, Story, TextQuote, User, Voice,
)
from pydantic_ai.messages import ImageUrl

from kibernikto.telegram.pre_processors import TelegramMessagePreprocessor

NOW = datetime.now(timezone.utc)
CHAT = Chat(id=-100, type='supergroup', title='group')
BOT = User(id=100, is_bot=True, first_name='kibernikto', username='kiber_bot')
ALICE = User(id=1, is_bot=False, first_name='Alice', username='alice')
BOB = User(id=2, is_bot=False, first_name='Bob', last_name='Smith')
CHANNEL = Chat(id=-200, type='channel', title='News')
IMAGE = ImageUrl(url='https://img.test/x.jpg')
PHOTO = [PhotoSize(file_id='p', file_unique_id='p', width=1, height=1)]


def msg(message_id: int = 10, sender: User | None = ALICE, **fields) -> Message:
    return Message(message_id=message_id, date=NOW, chat=CHAT, from_user=sender, **fields)


def sticker() -> Sticker:
    return Sticker(file_id='s', file_unique_id='s', type='regular', width=1, height=1,
                   is_animated=False, is_video=False)


class PreprocessorReplyForwardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = Bot('100:offline-test-token')
        self.bot.session.make_request = AsyncMock(side_effect=AssertionError('no Telegram calls expected'))
        self.pre = TelegramMessagePreprocessor()
        # Media IO is stubbed: these tests own ordering and labels, not downloads.
        for name, result in (('_process_photo', lambda m: [IMAGE] if m.photo else []),
                             ('_process_voice', lambda m: ['[Voice transcription]: own'] if m.voice else [])):
            patcher = patch.object(self.pre, name, AsyncMock(side_effect=result))
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self) -> None:
        await self.bot.session.close()

    async def run_pre(self, message: Message) -> list | None:
        return await self.pre.process_tg_message(message.as_(self.bot))

    async def test_plain_text_is_unchanged(self) -> None:
        self.assertEqual(await self.run_pre(msg(text='hi')), ['hi'])

    async def test_reply_puts_quote_before_own_caption_and_photo(self) -> None:
        parts = await self.run_pre(msg(reply_to_message=msg(1, sender=BOB, text='original'),
                                       caption='look', photo=PHOTO))
        self.assertEqual(parts, ["[Replying to Bob Smith's message]:", 'original', '[End of quoted message]',
                                 'look', IMAGE])

    async def test_reply_to_sticker_never_replies_to_quoted_message(self) -> None:
        parts = await self.run_pre(msg(reply_to_message=msg(1, sender=BOB, sticker=sticker()), text='lol'))
        self.assertEqual(parts, ["[Replying to Bob Smith's message]:", '[sticker]', '[End of quoted message]', 'lol'])
        self.bot.session.make_request.assert_not_called()

    async def test_quoted_voice_is_marked_not_transcribed(self) -> None:
        voice = Voice(file_id='v', file_unique_id='v', duration=3)
        parts = await self.run_pre(msg(reply_to_message=msg(1, sender=BOB, voice=voice), text='?'))
        self.assertEqual(parts, ["[Replying to Bob Smith's message]:", '[voice]', '[End of quoted message]', '?'])
        self.assertEqual(self.pre._process_voice.await_count, 1)

    async def test_quoted_photo_is_still_visible(self) -> None:
        parts = await self.run_pre(msg(reply_to_message=msg(1, sender=BOB, photo=PHOTO, caption='cat'), text='?'))
        self.assertEqual(parts, ["[Replying to Bob Smith's message]:", 'cat', IMAGE, '[End of quoted message]', '?'])

    async def test_reply_to_bot_keeps_only_header(self) -> None:
        parts = await self.run_pre(msg(reply_to_message=msg(1, sender=BOT, text='long answer'), text='more'))
        self.assertEqual(parts, ["[Replying to bot (you)'s message]", 'more'])

    async def test_quote_replaces_full_replied_text(self) -> None:
        for sender, author in ((BOB, 'Bob Smith'), (BOT, 'bot (you)')):
            with self.subTest(author=author):
                parts = await self.run_pre(msg(reply_to_message=msg(1, sender=sender, text='a b c'),
                                               quote=TextQuote(text='b', position=2), text='why?'))
                self.assertEqual(parts, [f"[Replying to {author}'s message, quoted fragment]:", 'b',
                                         '[End of quoted message]', 'why?'])

    async def test_sender_chat_wins_over_placeholder_user(self) -> None:
        anon = User(id=1087968824, is_bot=True, first_name='Group', username='GroupAnonymousBot')
        parts = await self.run_pre(msg(reply_to_message=msg(1, sender=anon, sender_chat=CHANNEL, text='post'),
                                       text='ok'))
        self.assertEqual(parts[0], "[Replying to News's message]:")

    async def test_forum_topic_root_is_not_a_reply(self) -> None:
        root = msg(1, forum_topic_created={'name': 'topic', 'icon_color': 0})
        self.assertEqual(await self.run_pre(msg(reply_to_message=root, text='hi')), ['hi'])

    async def test_external_reply_uses_origin_and_quote(self) -> None:
        external = ExternalReplyInfo(origin=MessageOriginChannel(date=NOW, chat=CHANNEL, message_id=7),
                                     chat=CHANNEL, message_id=7)
        parts = await self.run_pre(msg(external_reply=external, quote=TextQuote(text='claim', position=0),
                                       text='true?'))
        self.assertEqual(parts, ["[Replying to News (message #7) in another chat's message, quoted fragment]:",
                                 'claim', '[End of quoted message]', 'true?'])

    async def test_external_reply_without_quote_lists_media(self) -> None:
        external = ExternalReplyInfo(origin=MessageOriginUser(date=NOW, sender_user=BOB), sticker=sticker())
        parts = await self.run_pre(msg(external_reply=external, text='?'))
        self.assertEqual(parts, ["[Replying to Bob Smith in another chat's message]:", '[sticker]',
                                 '[End of quoted message]', '?'])

    async def test_reply_to_story(self) -> None:
        parts = await self.run_pre(msg(reply_to_story=Story(chat=CHANNEL, id=3), text='nice'))
        self.assertEqual(parts, ['[Replying to a story from News]', 'nice'])

    async def test_forward_wraps_all_own_content(self) -> None:
        origin = MessageOriginUser(date=NOW, sender_user=BOB)
        parts = await self.run_pre(msg(forward_origin=origin, photo=PHOTO, caption='meme'))
        self.assertEqual(parts, ['[Forwarded from Bob Smith]:', 'meme', IMAGE, '[End of forwarded message]'])

    async def test_forward_origin_labels(self) -> None:
        cases = (
            (MessageOriginUser(date=NOW, sender_user=ALICE), '@alice'),
            (MessageOriginChat(date=NOW, sender_chat=CHAT), 'group'),
            (MessageOriginChannel(date=NOW, chat=CHANNEL, message_id=9), 'News (message #9)'),
            (MessageOriginHiddenUser(date=NOW, sender_user_name='Ghost'), 'Ghost'),
        )
        for origin, label in cases:
            with self.subTest(label=label):
                parts = await self.run_pre(msg(forward_origin=origin, text='x'))
                self.assertEqual(parts, [f'[Forwarded from {label}]:', 'x', '[End of forwarded message]'])

    async def test_missing_from_user_does_not_crash(self) -> None:
        self.assertEqual(await self.run_pre(msg(sender=None, sender_chat=CHANNEL, text='post')), ['post'])


if __name__ == '__main__':
    unittest.main()
