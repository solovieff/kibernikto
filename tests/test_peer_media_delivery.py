"""Telegram permits neither single-item albums nor mixed file/audio albums."""
import unittest
from unittest.mock import AsyncMock
from tests.test_telegram_peer import message
from aiogram import Bot
from aiogram.methods import SendDocument, SendAudio, SendMessage
from pydantic_ai.messages import BinaryContent
from pydantic_ai.models.test import TestModel
from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.telegram.utils.conversation import reply


class MediaDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_wav_is_sent_as_document_not_unsupported_telegram_audio(self):
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        bot.session.make_request = AsyncMock(return_value=message(10))
        incoming = message(1, sender=300, chat_id=300).model_copy(update={
            'from_user': message(1).from_user.model_copy(update={'id': 300, 'is_bot': False})}).as_(bot)
        agent = KiberniktoAgent(model=TestModel(custom_output_text='done'), history_storage=None)
        result = await agent.run('task', deps=TelegramDeps(attachments=[BinaryContent(
            data=b'RIFF', media_type='audio/wav', vendor_metadata={'filename': 'tone.wav'})]))
        await reply(incoming, result)
        method = bot.session.make_request.await_args.args[1]
        self.assertIsInstance(method, SendDocument)
        self.assertEqual(method.document.filename, 'tone.wav')

    async def test_single_file_and_mixed_audio_deliver_individually_with_names(self):
        bot = Bot('100:offline-test-token')
        self.addAsyncCleanup(bot.session.close)
        bot.session.make_request = AsyncMock(return_value=message(10))
        incoming = message(1, sender=300, chat_id=300).model_copy(update={
            'from_user': message(1).from_user.model_copy(update={'id': 300, 'is_bot': False})}).as_(bot)
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                bot.session.make_request.reset_mock()
                attachments = [BinaryContent(data=b'report', media_type='text/plain', vendor_metadata={'filename': 'résumé.txt'})]
                if mixed:
                    attachments.append(BinaryContent(data=b'audio', media_type='audio/mpeg', vendor_metadata={'filename': 'tone.mp3'}))
                agent = KiberniktoAgent(model=TestModel(custom_output_text='full answer'), history_storage=None)
                result = await agent.run('task', deps=TelegramDeps(attachments=attachments))
                await reply(incoming, result)
                methods = [c.args[1] for c in bot.session.make_request.await_args_list]
                self.assertIsInstance(methods[0], SendMessage)
                self.assertIsInstance(methods[1], SendDocument)
                self.assertEqual(methods[1].document.filename, 'résumé.txt')
                self.assertEqual(methods[1].document.data, b'report')
                self.assertEqual(methods[1].reply_parameters.message_id, 1)
                if mixed:
                    self.assertIsInstance(methods[2], SendAudio)
                    self.assertEqual(methods[2].audio.filename, 'tone.mp3')
