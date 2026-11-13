"""Voice reply mode and speech delivery regressions."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.types import Chat, Message, User
from datetime import datetime, timezone
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.messages import FilePart
from pydantic_ai.models.test import TestModel

from kibernikto.ai.agent.telegram.telegram_agent import build_telegram_agent
from kibernikto.storage.models import ConversationInfo
from kibernikto.telegram.utils.conversation import reply


class VoiceModeTests(unittest.TestCase):
    def test_empty_provider_options_env_is_disabled(self):
        import os
        from kibernikto.ai.speech import SpeechSettings
        with patch.dict(os.environ, {'TTS_OPENAI_API_PROVIDER_OPTIONS': ''}):
            self.assertIsNone(SpeechSettings(_env_file=None).API_PROVIDER_OPTIONS)

    def test_existing_chat_defaults_to_text(self):
        info = ConversationInfo.model_validate({'credits': 12})
        self.assertEqual(info.response_mode, 'text')
        self.assertEqual(info.credits, 12)


class VoiceDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_store_keeps_mode_and_credits_for_each_chat(self):
        import tempfile
        from pathlib import Path
        from kibernikto.storage.file.chat_data import ChatDataStorage
        with tempfile.TemporaryDirectory() as root:
            store = ChatDataStorage(root=Path(root))
            await store.save('42', ConversationInfo(credits=12, response_mode='audio'))
            await store.save('43', ConversationInfo(credits=99))
            self.assertEqual((await store.load('42')).response_mode, 'audio')
            self.assertEqual((await store.load('42')).credits, 12)
            self.assertEqual((await store.load('43')).response_mode, 'text')

    async def test_speech_service_uses_openai_compatible_api(self):
        import json
        import httpx2
        from openai import AsyncOpenAI
        from pydantic import SecretStr
        from kibernikto.ai import speech

        requests = []
        client_options = []
        def handler(request):
            requests.append(request)
            return httpx2.Response(200, headers={'content-type': 'audio/mpeg'}, content=b'ID3audio')
        def make_client(**kwargs):
            client_options.append(kwargs)
            return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
        with patch.object(speech.SPEECH_SETTINGS, 'API_KEY', SecretStr('test-key')), \
             patch.object(speech, 'AsyncOpenAI', side_effect=make_client):
            self.assertEqual(await speech.synthesize_speech('Hello'), b'ID3audio')
        self.assertEqual(client_options[0].get('timeout'), 30.0)
        self.assertEqual(client_options[0].get('max_retries'), 0)
        self.assertEqual(requests[0].url.path, '/api/v1/audio/speech')
        body = json.loads(requests[0].content)
        self.assertEqual(body['input'], '[tired] [low, gravelly] [cynical] [dark] Hello')
        self.assertEqual(body['model'], 'elevenlabs/eleven-v4')
        self.assertEqual(body['response_format'], 'mp3')
        self.assertEqual(body['voice'], 'adam')
        self.assertNotIn('provider', body)

    async def test_speech_service_has_hard_deadline(self):
        import asyncio
        from pydantic import SecretStr
        from kibernikto.ai import speech

        async def slow_create(**kwargs):
            await asyncio.sleep(0.1)
            return SimpleNamespace(content=b'ID3audio')

        client = AsyncMock()
        client.__aenter__.return_value.audio.speech.create.side_effect = slow_create
        with patch.object(speech.SPEECH_SETTINGS, 'API_KEY', SecretStr('test-key')), \
             patch.object(speech, 'TTS_TIMEOUT_SECONDS', 0.01), \
             patch.object(speech, 'AsyncOpenAI', return_value=client):
            with self.assertRaises(TimeoutError):
                await speech.synthesize_speech('Hello')

    async def test_optional_provider_options_are_loaded_from_env_and_sent(self):
        import json
        import os
        import httpx2
        from openai import AsyncOpenAI
        from pydantic import SecretStr
        from kibernikto.ai import speech

        options = {'elevenlabs': {'voice_settings': {'stability': 0.4, 'similarity_boost': 0.75}}}
        with patch.dict(os.environ, {'TTS_OPENAI_API_PROVIDER_OPTIONS': json.dumps(options)}):
            settings = speech.SpeechSettings(_env_file=None, API_KEY=SecretStr('test-key'))
        requests = []
        def handler(request):
            requests.append(request)
            return httpx2.Response(200, headers={'content-type': 'audio/mpeg'}, content=b'ID3audio')
        def make_client(**kwargs):
            return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
        with patch.object(speech, 'SPEECH_SETTINGS', settings), patch.object(speech, 'AsyncOpenAI', side_effect=make_client):
            self.assertEqual(await speech.synthesize_speech('Hello'), b'ID3audio')
        self.assertEqual(json.loads(requests[0].content)['provider']['options'], options)

    async def test_toggle_enables_voice_then_restores_text(self):
        from kibernikto.telegram.handlers.commands import cmd_toggle_voice
        state = ConversationInfo(credits=12)
        store = SimpleNamespace(load=AsyncMock(return_value=state), save=AsyncMock())
        message = SimpleNamespace(chat=SimpleNamespace(id=42, type='private'),
                                  from_user=SimpleNamespace(is_bot=False),
                                  bot=SimpleNamespace(send_voice=AsyncMock()), answer=AsyncMock(), message_id=7)
        with patch('kibernikto.telegram.handlers.commands.chat_data', store), \
             patch('kibernikto.telegram.handlers.commands.synthesize_speech', new_callable=AsyncMock,
                   return_value=b'ID3test') as synth:
            await cmd_toggle_voice(message)
            self.assertEqual(state.response_mode, 'audio')
            message.bot.send_voice.assert_awaited_once()
            synth.assert_awaited_once()
            await cmd_toggle_voice(message)
        self.assertEqual(state.response_mode, 'text')
        message.answer.assert_awaited_once()
        self.assertEqual(state.credits, 12)
        self.assertEqual(store.save.await_count, 2)

    async def test_toggle_explains_telegram_voice_privacy_restriction(self):
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.methods import SendVoice
        from kibernikto.telegram.handlers.commands import cmd_toggle_voice
        state = ConversationInfo(credits=12)
        store = SimpleNamespace(load=AsyncMock(return_value=state), save=AsyncMock())
        error = TelegramBadRequest(method=SendVoice(chat_id=42, voice='file'),
                                   message='Bad Request: user restricted receiving of voice note messages')
        message = SimpleNamespace(chat=SimpleNamespace(id=42, type='private'),
                                  from_user=SimpleNamespace(is_bot=False),
                                  bot=SimpleNamespace(send_voice=AsyncMock(side_effect=error)),
                                  answer=AsyncMock(), message_id=7)
        with patch('kibernikto.telegram.handlers.commands.chat_data', store), \
             patch('kibernikto.telegram.handlers.commands.synthesize_speech', new_callable=AsyncMock,
                   return_value=b'ID3test'), self.assertLogs('kibernikto.telegram.handlers.commands'):
            await cmd_toggle_voice(message)
        self.assertEqual(state.response_mode, 'text')
        explanation = message.answer.await_args.args[0]
        self.assertIn('конфиденциальност', explanation.lower())
        self.assertIn('голосов', explanation.lower())
        self.assertIn('текстом', explanation.lower())

    async def test_voice_delivery_error_reverts_text_mode(self):
        from kibernikto.telegram.handlers.commands import cmd_toggle_voice
        state = ConversationInfo(credits=12)
        store = SimpleNamespace(load=AsyncMock(return_value=state), save=AsyncMock())
        message = SimpleNamespace(chat=SimpleNamespace(id=42, type='private'),
                                  from_user=SimpleNamespace(is_bot=False),
                                  bot=SimpleNamespace(send_voice=AsyncMock(side_effect=OSError('offline'))),
                                  answer=AsyncMock(), message_id=7)
        with patch('kibernikto.telegram.handlers.commands.chat_data', store), \
             patch('kibernikto.telegram.handlers.commands.synthesize_speech', new_callable=AsyncMock,
                   return_value=b'ID3test'), self.assertLogs('kibernikto.telegram.handlers.commands'):
            await cmd_toggle_voice(message)
        self.assertEqual(state.response_mode, 'text')
        self.assertEqual(store.save.await_count, 2)
        message.answer.assert_awaited_once()

    async def test_toggle_times_out_and_keeps_text_mode(self):
        import asyncio
        from pydantic import SecretStr
        from kibernikto.ai import speech
        from kibernikto.telegram.handlers.commands import cmd_toggle_voice

        async def slow_create(**kwargs):
            await asyncio.sleep(0.1)
            return SimpleNamespace(content=b'ID3audio')

        client = AsyncMock()
        client.__aenter__.return_value.audio.speech.create.side_effect = slow_create
        state = ConversationInfo(credits=12)
        store = SimpleNamespace(load=AsyncMock(return_value=state), save=AsyncMock())
        message = SimpleNamespace(chat=SimpleNamespace(id=42, type='private'),
                                  from_user=SimpleNamespace(is_bot=False),
                                  bot=SimpleNamespace(send_voice=AsyncMock()), answer=AsyncMock(), message_id=7)
        with patch('kibernikto.telegram.handlers.commands.chat_data', store), \
             patch.object(speech.SPEECH_SETTINGS, 'API_KEY', SecretStr('test-key')), \
             patch.object(speech, 'TTS_TIMEOUT_SECONDS', 0.01), \
             patch.object(speech, 'AsyncOpenAI', return_value=client), \
             self.assertLogs('kibernikto.telegram.handlers.commands'):
            await cmd_toggle_voice(message)
        self.assertEqual(state.response_mode, 'text')
        store.save.assert_not_awaited()
        message.bot.send_voice.assert_not_awaited()
        message.answer.assert_awaited_once()

    async def test_failure_to_synthesize_leaves_text_mode(self):
        from kibernikto.telegram.handlers.commands import cmd_toggle_voice
        state = ConversationInfo(credits=12)
        store = SimpleNamespace(load=AsyncMock(return_value=state), save=AsyncMock())
        message = SimpleNamespace(chat=SimpleNamespace(id=42, type='private'),
                                  from_user=SimpleNamespace(is_bot=False),
                                  bot=SimpleNamespace(send_voice=AsyncMock()), answer=AsyncMock(), message_id=7)
        with patch('kibernikto.telegram.handlers.commands.chat_data', store), \
             patch('kibernikto.telegram.handlers.commands.synthesize_speech', new_callable=AsyncMock,
                   side_effect=ValueError('offline')), self.assertLogs('kibernikto.telegram.handlers.commands'):
            await cmd_toggle_voice(message)
        self.assertEqual(state.response_mode, 'text')
        store.save.assert_not_awaited()
        message.bot.send_voice.assert_not_awaited()
        message.answer.assert_awaited_once()

    async def test_text_and_bot_messages_never_synthesize(self):
        from kibernikto.ai.agent.telegram.deps import TelegramDeps
        bot = AsyncMock(spec=Bot)
        agent = build_telegram_agent(model=TestModel(custom_output_text='Hello'), history_storage=None, persona=False)
        with patch('kibernikto.ai.agent.telegram.speech_reply.synthesize_speech', new_callable=AsyncMock) as synth:
            for mode, is_bot, billable in [('text', False, True), ('audio', True, True), ('audio', False, False)]:
                message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                                  from_user=User(id=42, is_bot=is_bot, first_name='User'), text='hello').as_(bot)
                deps = TelegramDeps(message=message, chat_info=ConversationInfo(response_mode=mode), billable=billable)
                result = await agent.run('hello', deps=deps, conversation_id='42')
                self.assertEqual(result.output, 'Hello')
                self.assertFalse(result.response.files)
            synth.assert_not_awaited()

    async def test_synthesis_failure_keeps_original_response(self):
        from kibernikto.ai.agent.telegram.deps import TelegramDeps
        bot = AsyncMock(spec=Bot)
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        deps = TelegramDeps(message=message, chat_info=ConversationInfo(response_mode='audio'))
        agent = build_telegram_agent(model=TestModel(custom_output_text='Hello'), history_storage=None, persona=False)
        with patch('kibernikto.ai.agent.telegram.speech_reply.synthesize_speech', new_callable=AsyncMock,
                   side_effect=ValueError('offline')), self.assertLogs('kibernikto.ai.agent.telegram.speech_reply'):
            result = await agent.run('hello', deps=deps, conversation_id='42')
        self.assertEqual(result.output, 'Hello')
        self.assertFalse(result.response.files)

    async def test_long_voice_reply_has_one_deadline_for_all_chunks(self):
        import asyncio
        from kibernikto.ai.agent.telegram import speech_reply
        from kibernikto.ai.agent.telegram.deps import TelegramDeps

        async def slow_chunk(text):
            await asyncio.sleep(0.03)
            return b'ID3test'

        bot = AsyncMock(spec=Bot)
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        deps = TelegramDeps(message=message, chat_info=ConversationInfo(response_mode='audio'))
        agent = build_telegram_agent(model=TestModel(call_tools=[], custom_output_text='X' * 10000),
                                     history_storage=None, persona=False)
        with patch.object(speech_reply, 'TTS_TIMEOUT_SECONDS', 0.04, create=True), \
             patch.object(speech_reply, 'synthesize_speech', side_effect=slow_chunk), \
             patch.object(speech_reply.logger, 'exception'):
            result = await agent.run('hello', deps=deps, conversation_id='42')
        self.assertEqual(result.output, 'X' * 10000)
        self.assertFalse(result.response.files)

    async def test_original_text_remains_in_history(self):
        from kibernikto.ai.agent.telegram.deps import TelegramDeps
        from kibernikto.storage.base import MemoryHistoryStorage
        bot = AsyncMock(spec=Bot)
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        deps = TelegramDeps(message=message, chat_info=ConversationInfo(response_mode='audio'))
        store = MemoryHistoryStorage()
        agent = build_telegram_agent(model=TestModel(custom_output_text='Hello'), history_storage=store, persona=False)
        with patch('kibernikto.ai.agent.telegram.speech_reply.synthesize_speech', new_callable=AsyncMock,
                   return_value=b'ID3test'):
            result = await agent.run('hello', deps=deps, conversation_id='42')
        history = await store.get_full_conversation('42')
        self.assertTrue(any(getattr(part, 'content', None) == 'Hello' for msg in history for part in msg.parts))
        self.assertFalse(any(isinstance(part, FilePart) for msg in history for part in msg.parts))
        self.assertTrue(result.response.files)

    async def test_tts_failure_strips_delivery_tags_from_text(self):
        from kibernikto.ai.agent.telegram.deps import TelegramDeps
        bot = AsyncMock(spec=Bot)
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        deps = TelegramDeps(message=message, chat_info=ConversationInfo(response_mode='audio'))
        agent = build_telegram_agent(model=TestModel(custom_output_text='[sarcastic] Hello [link](https://example.org)'),
                                     history_storage=None, persona=False)
        with patch('kibernikto.ai.agent.telegram.speech_reply.synthesize_speech', new_callable=AsyncMock,
                   side_effect=ValueError('offline')), self.assertLogs('kibernikto.ai.agent.telegram.speech_reply'):
            result = await agent.run('hello', deps=deps, conversation_id='42')
        self.assertEqual(result.output, 'Hello [link](https://example.org)')

    async def test_voice_instruction_present_only_in_voice_mode(self):
        from pydantic_ai import ModelResponse, TextPart
        from pydantic_ai.models.function import FunctionModel
        from kibernikto.ai.agent.telegram.deps import TelegramDeps
        observed = []
        def model(messages, info):
            observed.append(info.instructions or '')
            return ModelResponse(parts=[TextPart('Hello')])
        bot = AsyncMock(spec=Bot)
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        agent = build_telegram_agent(model=FunctionModel(model), history_storage=None, persona=False)
        with patch('kibernikto.ai.agent.telegram.speech_reply.synthesize_speech', new_callable=AsyncMock,
                   return_value=b'ID3test'):
            for mode in ('text', 'audio'):
                await agent.run('hello', deps=TelegramDeps(message=message, chat_info=ConversationInfo(response_mode=mode)),
                                conversation_id='42')
        self.assertNotIn('voice delivery tags', observed[0])
        self.assertIn('voice delivery tags', observed[1])
        self.assertIn('avoid unnecessary Markdown', observed[1])
        self.assertIn('Keep necessary links', observed[1])

    async def test_audio_chat_synthesizes_agent_answer(self):
        from kibernikto.ai.agent.telegram.deps import TelegramDeps
        bot = AsyncMock(spec=Bot)
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        deps = TelegramDeps(message=message, chat_info=ConversationInfo(response_mode='audio'))
        agent = build_telegram_agent(model=TestModel(custom_output_text='Hello'), history_storage=None, persona=False)
        with patch('kibernikto.ai.agent.telegram.speech_reply.synthesize_speech', new_callable=AsyncMock,
                   return_value=b'ID3test') as synth:
            result = await agent.run('hello', deps=deps, conversation_id='42')
        self.assertEqual(result.output, 'Hello')
        synth.assert_awaited_once_with('Hello')
        self.assertEqual(result.response.files[0].data, b'ID3test')
        self.assertTrue(result.response.files[0].vendor_metadata['telegram_voice'])

    async def test_reply_explains_voice_restriction_and_preserves_answer(self):
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.methods import SendVoice
        bot = AsyncMock(spec=Bot)
        bot.send_voice.side_effect = TelegramBadRequest(
            method=SendVoice(chat_id=42, voice='file'),
            message='Bad Request: user restricted receiving of voice note messages',
        )
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        result = await Agent(TestModel(custom_output_text='Hello')).run('hello')
        result.response.parts.append(FilePart(content=BinaryContent(
            data=b'ID3test', media_type='audio/mpeg', vendor_metadata={'telegram_voice': True})))
        with self.assertLogs('kibernikto.telegram.utils.conversation'):
            await reply(message, result)
        sent = [call.args[0].text for call in bot.await_args_list]
        self.assertTrue(any('конфиденциальност' in text.lower() for text in sent))
        self.assertTrue(any('Hello' in text for text in sent))

    async def test_links_stay_clickable_in_voice_mode(self):
        bot = AsyncMock(spec=Bot)
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        result = await Agent(TestModel(custom_output_text='Link: https://example.org')).run('hello')
        result.response.parts.append(FilePart(content=BinaryContent(
            data=b'ID3test', media_type='audio/mpeg', vendor_metadata={'telegram_voice': True})))
        await reply(message, result)
        bot.send_voice.assert_awaited_once()
        # message.reply uses Bot.__call__, unlike the direct send_voice call.
        bot.assert_awaited_once()
        self.assertIn('https://example.org', bot.await_args.args[0].text)

    async def test_agent_to_telegram_voice_delivery(self):
        from kibernikto.ai.agent.telegram.deps import TelegramDeps
        bot = AsyncMock(spec=Bot)
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        deps = TelegramDeps(message=message, chat_info=ConversationInfo(response_mode='audio'))
        agent = build_telegram_agent(model=TestModel(custom_output_text='Hello'), history_storage=None, persona=False)
        with patch('kibernikto.ai.agent.telegram.speech_reply.synthesize_speech', new_callable=AsyncMock,
                   return_value=b'ID3test'):
            result = await agent.run('hello', deps=deps, conversation_id='42')
        await reply(message, result)
        bot.send_voice.assert_awaited_once()
        bot.send_audio.assert_not_awaited()
        bot.assert_not_awaited()

    async def test_marked_audio_is_sent_as_voice_not_text_or_music(self):
        bot = AsyncMock(spec=Bot)
        message = Message(message_id=7, date=datetime.now(timezone.utc), chat=Chat(id=42, type='private'),
                          from_user=User(id=42, is_bot=False, first_name='User'), text='hello').as_(bot)
        result = await Agent(TestModel(custom_output_text='Hello')).run('hello')
        result.response.parts.append(FilePart(content=BinaryContent(
            data=b'ID3test', media_type='audio/mpeg', vendor_metadata={'telegram_voice': True})))
        await reply(message, result)
        bot.send_voice.assert_awaited_once()
        bot.send_audio.assert_not_awaited()
        bot.send_message.assert_not_awaited()
