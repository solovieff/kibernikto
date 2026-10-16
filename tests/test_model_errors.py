"""Offline regressions: provider errors reach chat as short user messages, never raw bodies."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram.types import Chat, Message, User
from pydantic_ai import ModelHTTPError

from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.ai.agent.core.errors import InsufficientCreditsError, RULES, map_model_error
from kibernikto.ai.agent.telegram.telegram_agent import user_facing_model_error

IMAGE_BODY = {'message': 'No endpoints found that support image input', 'code': 404,
              'metadata': {'routing_funnel': [{'step': 'Initial Endpoints', 'endpoint_count': 6}],
                           'failed_routing_step': 'Filter by Image Support'}}


class MapModelErrorTests(unittest.TestCase):
    def test_image_routing_failure_is_its_own_category(self) -> None:
        info = map_model_error(ModelHTTPError(404, 'm', IMAGE_BODY))
        self.assertEqual(info.category, 'no_image_support')

    def test_plain_404_is_model_not_found_not_image_error(self) -> None:
        info = map_model_error(ModelHTTPError(404, 'm', {'message': 'No such model'}))
        self.assertEqual(info.category, 'model_not_found')

    def test_status_codes_map_to_categories(self) -> None:
        cases = {429: 'rate_limited', 401: 'access_denied', 403: 'access_denied', 400: 'bad_request',
                 413: 'bad_request', 503: 'provider_unavailable', 502: 'provider_unavailable'}
        for status, category in cases.items():
            with self.subTest(status=status):
                self.assertEqual(map_model_error(ModelHTTPError(status, 'm', {'message': 'x'})).category, category)

    def test_unknown_status_falls_back_without_leaking_body(self) -> None:
        info = map_model_error(ModelHTTPError(418, 'm', {'secret': 'provider internals'}))
        self.assertEqual(info.category, 'unknown')
        self.assertNotIn('provider internals', info.user_message)

    def test_every_category_message_is_safe_for_chat(self) -> None:
        for rule in RULES:
            with self.subTest(category=rule.info.category):
                self.assertNotIn('<', rule.info.user_message)
                self.assertNotIn('{', rule.info.user_message)


class UserFacingModelErrorTests(unittest.TestCase):
    def test_image_routing_failure_gets_clear_hint(self) -> None:
        text = user_facing_model_error(ModelHTTPError(404, 'm', IMAGE_BODY))
        self.assertIn('картинк', text)
        self.assertNotIn('routing', text)
        self.assertNotIn('endpoint', text)

    def test_status_codes_map_to_short_messages(self) -> None:
        cases = {429: 'перегружена', 401: 'доступе', 403: 'доступе', 503: 'недоступна'}
        for status, fragment in cases.items():
            with self.subTest(status=status):
                self.assertIn(fragment, user_facing_model_error(ModelHTTPError(status, 'm', {'message': 'x'})))

    def test_unknown_error_hides_raw_body(self) -> None:
        text = user_facing_model_error(ModelHTTPError(418, 'm', {'secret': 'provider internals'}))
        self.assertNotIn('provider internals', text)
        self.assertNotIn('418', text)


def _private_message() -> Message:
    user = User(id=5, is_bot=False, first_name='u')
    chat = Chat(id=5, type='private')
    return Message(message_id=1, date=datetime.now(timezone.utc), chat=chat, from_user=user, text='draw')


class ProcessMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_exhausted_credits_return_top_up_hint_without_error(self) -> None:
        from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent

        agent = TelegramAgent(model=None, history_storage=None)
        message = _private_message()
        with patch.object(agent, '_pre_processor', AsyncMock(process_tg_message=AsyncMock(return_value=['hi']))), \
                patch.object(agent, 'build_deps', AsyncMock(return_value=TelegramDeps(message=message))), \
                patch.object(agent, 'run', AsyncMock(side_effect=InsufficientCreditsError())):
            result = await agent.process_message(message)
        self.assertIn('/pay', result)
        self.assertIn('/balance', result)

    async def test_model_error_propagates_to_dispatcher(self) -> None:
        from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent

        agent = TelegramAgent(model=None, history_storage=None)
        message = _private_message()
        error = ModelHTTPError(404, 'm', IMAGE_BODY)
        with patch.object(agent, '_pre_processor', AsyncMock(process_tg_message=AsyncMock(return_value=['draw']))), \
                patch.object(agent, 'build_deps', AsyncMock(return_value=TelegramDeps(message=message))), \
                patch.object(agent, 'run', AsyncMock(side_effect=error)):
            with self.assertRaises(ModelHTTPError):
                await agent.process_message(message)


class ConversationHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_hints_user_and_reraises_model_error(self) -> None:
        from kibernikto.telegram.handlers import conversation

        message = _private_message()
        agent = AsyncMock()
        agent.process_message = AsyncMock(side_effect=ModelHTTPError(404, 'm', IMAGE_BODY))
        with patch.object(Message, 'answer', new_callable=AsyncMock) as answer, \
                patch.object(Message, 'bot', new_callable=lambda: AsyncMock(), create=True), \
                patch.object(conversation._agent_module, 'get_telegram_agent', return_value=agent):
            with self.assertRaises(ModelHTTPError):
                await conversation._process_and_reply(message)
        hint = answer.await_args.args[0]
        self.assertIn('картинк', hint)
        self.assertNotIn('failed_routing_step', hint)
        agent.reply_to.assert_not_awaited()

    async def test_handler_generic_hint_for_other_errors(self) -> None:
        from kibernikto.telegram.handlers import conversation

        message = _private_message()
        agent = AsyncMock()
        agent.process_message = AsyncMock(side_effect=RuntimeError('boom'))
        with patch.object(Message, 'answer', new_callable=AsyncMock) as answer, \
                patch.object(Message, 'bot', new_callable=lambda: AsyncMock(), create=True), \
                patch.object(conversation._agent_module, 'get_telegram_agent', return_value=agent):
            with self.assertRaises(RuntimeError):
                await conversation._process_and_reply(message)
        self.assertIn('администратор', answer.await_args.args[0])


if __name__ == '__main__':
    unittest.main()
