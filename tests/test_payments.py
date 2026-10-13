"""Offline Stars regressions with real aiogram objects and mocked transport."""

from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import AsyncMock, patch

# Keep import-time model/storage singletons independent of live credentials.
os.environ['OPENROUTER_API_KEY'] = 'test-not-a-real-key'
os.environ['AGENT_KIBERNIKTO_MODEL_NAME'] = 'openrouter:test/offline'
os.environ['APP_STORAGE_DATA_BACKEND'] = 'file'
os.environ['APP_STORAGE_MEDIA_BACKEND'] = 'file'

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Chat, Message, PreCheckoutQuery, StarTransaction, StarTransactions, SuccessfulPayment, Update, User

from aiogram.filters import CommandObject

from kibernikto.storage.models import ConversationInfo
from kibernikto.telegram.config import TELEGRAM_SETTINGS
from kibernikto.telegram.handlers.payments import cmd_balance, cmd_pay, handle_pre_checkout, handle_successful_payment
from kibernikto.telegram.middleware.middleware_subscription import SUBSCRIPTION_SETTINGS
from kibernikto.telegram.payment.payment_utils import (DEFAULT_SUBSCRIPTION_PERIOD, SUBSCRIPTION_PAYLOAD, TOPUP_PAYLOAD,
                                                       check_sub, create_payment_link)


USER = User(id=200, is_bot=False, first_name='payer')


def transaction(identifier: str = 'charge', *, days: int = 1, user: int = 200,
                payload: str = SUBSCRIPTION_PAYLOAD, refund: bool = False) -> StarTransaction:
    partner = {'type': 'user', 'transaction_type': 'invoice_payment',
               'user': USER.model_copy(update={'id': user}), 'invoice_payload': payload,
               'subscription_period': DEFAULT_SUBSCRIPTION_PERIOD}
    return StarTransaction(id=identifier, amount=52, date=datetime.now(timezone.utc) - timedelta(days=days),
                           source=None if refund else partner, receiver=partner if refund else None)


class MemoryChatData:
    """In-memory ChatDataStore: round-trips through JSON like the real backends."""

    def __init__(self) -> None:
        self.rows: dict[int, str] = {}

    async def load(self, chat_id: int) -> ConversationInfo:
        row = self.rows.get(chat_id)
        return ConversationInfo.model_validate_json(row) if row else ConversationInfo()

    async def save(self, chat_id: int, info: ConversationInfo) -> None:
        self.rows[chat_id] = info.model_dump_json()


def paid_message(bot: Bot, *, amount: int = 52, payload: str = TOPUP_PAYLOAD, charge: str = 'charge',
                 currency: str = 'XTR') -> Message:
    payment = SuccessfulPayment(currency=currency, total_amount=amount, invoice_payload=payload,
                                telegram_payment_charge_id=charge, provider_payment_charge_id='')
    return Message(message_id=1, date=datetime.now(timezone.utc), from_user=USER,
                   chat=Chat(id=200, type='private'), successful_payment=payment).as_(bot)


class PaymentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = Bot('100:offline-test-token')
        self.bot.session.make_request = AsyncMock(return_value=True)
        self.addAsyncCleanup(self.bot.session.close)
        # Never touch the real ~/.kibernikto chat bucket from tests.
        self.chat_data = MemoryChatData()
        patcher = patch('kibernikto.telegram.handlers.payments.chat_data', self.chat_data)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_invoice_preserves_payload_and_period(self) -> None:
        with patch.object(self.bot, 'create_invoice_link', new=AsyncMock(return_value='link')) as create:
            self.assertEqual(await create_payment_link(self.bot, 52), 'link')
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['payload'], SUBSCRIPTION_PAYLOAD)
        self.assertEqual(kwargs['currency'], 'XTR')
        self.assertEqual(kwargs['subscription_period'], DEFAULT_SUBSCRIPTION_PERIOD)
        self.assertEqual(kwargs['prices'][0].amount, 52)

    async def test_invalid_prices_never_call_telegram(self) -> None:
        for price in (0, -1, True, 10001, 1.5):
            with self.subTest(price=price), self.assertRaises(ValueError):
                await create_payment_link(self.bot, price)
        self.bot.session.make_request.assert_not_awaited()

    async def check(self, transactions: list[StarTransaction]) -> bool:
        with patch.object(self.bot, 'get_star_transactions', new=AsyncMock(
                return_value=StarTransactions(transactions=transactions))):
            return await check_sub(200, self.bot)

    async def test_active_and_expired_subscriptions(self) -> None:
        self.assertTrue(await self.check([transaction()]))
        self.assertFalse(await self.check([transaction(days=31)]))
        self.assertFalse(await self.check([transaction(days=-1)]))
        self.assertFalse(await self.check([]))

    async def test_unrelated_and_non_user_sources_are_ignored(self) -> None:
        unrelated = StarTransaction(id='other', amount=1, date=datetime.now(timezone.utc),
                                    source={'type': 'other'})
        self.assertFalse(await self.check([unrelated, transaction(user=300), transaction(payload='other')]))

    async def test_refund_invalidates_only_matching_payment(self) -> None:
        self.assertFalse(await self.check([transaction(), transaction(refund=True)]))
        self.assertTrue(await self.check([transaction(), transaction('other', refund=True)]))

    async def test_subscription_on_second_page(self) -> None:
        first = [transaction(str(index), user=300) for index in range(100)]
        with patch.object(self.bot, 'get_star_transactions', new=AsyncMock(side_effect=[
                StarTransactions(transactions=first), StarTransactions(transactions=[transaction()]),
        ])) as lookup:
            self.assertTrue(await check_sub(200, self.bot))
        self.assertEqual([call.kwargs for call in lookup.await_args_list],
                         [{'offset': 0, 'limit': 100}, {'offset': 100, 'limit': 100}])

    async def test_refund_on_later_page_is_not_missed(self) -> None:
        first = [transaction()] + [transaction(str(index), user=300) for index in range(99)]
        with patch.object(self.bot, 'get_star_transactions', new=AsyncMock(side_effect=[
                StarTransactions(transactions=first), StarTransactions(transactions=[transaction(refund=True)]),
        ])):
            self.assertFalse(await check_sub(200, self.bot))

    async def test_full_page_requires_empty_terminal_page(self) -> None:
        with patch.object(self.bot, 'get_star_transactions', new=AsyncMock(side_effect=[
                StarTransactions(transactions=[transaction(str(index)) for index in range(100)]),
                StarTransactions(transactions=[]),
        ])) as lookup:
            self.assertTrue(await check_sub(200, self.bot))
        self.assertEqual(lookup.await_count, 2)

    async def test_lookup_failure_propagates(self) -> None:
        with patch.object(self.bot, 'get_star_transactions', new=AsyncMock(side_effect=RuntimeError('offline'))):
            with self.assertRaises(RuntimeError):
                await check_sub(200, self.bot)

    async def test_checkout_validation(self) -> None:
        cases = [(True, 'XTR', SUBSCRIPTION_PAYLOAD, 52, True),
                 (True, 'XTR', SUBSCRIPTION_PAYLOAD, 247, True),
                 (True, 'XTR', SUBSCRIPTION_PAYLOAD, 390, True),
                 (False, 'XTR', SUBSCRIPTION_PAYLOAD, 52, False),
                 (True, 'USD', SUBSCRIPTION_PAYLOAD, 52, False),
                 (True, 'XTR', 'other', 52, False),
                 (True, 'XTR', SUBSCRIPTION_PAYLOAD, 1, False),
                 # Top-ups accept any 1..10000 Stars and do not depend on the subscription switch.
                 (False, 'XTR', TOPUP_PAYLOAD, 1, True),
                 (False, 'XTR', TOPUP_PAYLOAD, 777, True),
                 (False, 'XTR', TOPUP_PAYLOAD, 10001, False),
                 (False, 'USD', TOPUP_PAYLOAD, 52, False)]
        for enabled, currency, payload, amount, valid in cases:
            with self.subTest(enabled=enabled, currency=currency, payload=payload, amount=amount):
                query = PreCheckoutQuery(id='checkout', from_user=USER, currency=currency,
                                         total_amount=amount, invoice_payload=payload).as_(self.bot)
                with patch.multiple(SUBSCRIPTION_SETTINGS, ENABLED=enabled, BASE_PRICE_STARS=52,
                                    TRIAL_CREDITS=247, RICH_CREDITS=390):
                    await handle_pre_checkout(query)
                request = self.bot.session.make_request.await_args.args[1]
                self.assertEqual(request.ok, valid)
                self.assertEqual(request.error_message is not None, not valid)

    async def test_payment_update_is_consumed_before_conversation(self) -> None:
        dispatcher = Dispatcher()
        router = Router()
        router.message.register(handle_successful_payment, F.successful_payment)
        conversation = AsyncMock()

        async def process_conversation(message: Message) -> None:
            await conversation(message)

        router.message.register(process_conversation)
        dispatcher.include_router(router)
        payment = SuccessfulPayment(currency='XTR', total_amount=52, invoice_payload=SUBSCRIPTION_PAYLOAD,
                                    telegram_payment_charge_id='charge', provider_payment_charge_id='')
        message = Message(message_id=1, date=datetime.now(timezone.utc), from_user=USER,
                          chat=Chat(id=200, type='private'), successful_payment=payment)
        await dispatcher.feed_update(self.bot, Update(update_id=1, message=message))
        conversation.assert_not_awaited()
        self.bot.session.make_request.assert_awaited_once()

    async def test_unrelated_payment_does_not_acknowledge_subscription(self) -> None:
        payment = SuccessfulPayment(currency='USD', total_amount=52, invoice_payload='other',
                                    telegram_payment_charge_id='charge', provider_payment_charge_id='')
        message = Message(message_id=1, date=datetime.now(timezone.utc), from_user=USER,
                          chat=Chat(id=200, type='private'), successful_payment=payment).as_(self.bot)
        await handle_successful_payment(message)
        self.bot.session.make_request.assert_not_awaited()
        self.assertEqual(self.chat_data.rows, {})

    def sent(self) -> object:
        return self.bot.session.make_request.await_args.args[1]

    async def test_topup_adds_stars_as_credits_and_persists(self) -> None:
        start = (await self.chat_data.load(200)).credits
        await handle_successful_payment(paid_message(self.bot, amount=100, charge='a'))
        await handle_successful_payment(paid_message(self.bot, amount=5, charge='b'))
        self.assertEqual((await self.chat_data.load(200)).credits, start + 105)
        self.assertIn(f'Balance: {start + 105}', self.sent().text)

    async def test_subscription_payment_also_tops_up(self) -> None:
        start = (await self.chat_data.load(200)).credits
        await handle_successful_payment(paid_message(self.bot, amount=52, payload=SUBSCRIPTION_PAYLOAD))
        self.assertEqual((await self.chat_data.load(200)).credits, start + 52)

    def test_add_credits_rejects_negative(self) -> None:
        info = ConversationInfo(credits=0)
        self.assertEqual(info.add_credits(5), 5)
        with self.assertRaises(ValueError):
            info.add_credits(-1)

    def test_legacy_row_keys_are_ignored(self) -> None:
        legacy = '{"tg_id": 1, "credits": 7, "timezone": "Europe/Moscow", "client_app_info": "x", "paid_charge_ids": ["a"]}'
        self.assertEqual(ConversationInfo.model_validate_json(legacy).model_dump(), {'credits': 7})

    def command(self, text: str, chat_type: str = 'private') -> tuple[Message, CommandObject]:
        message = Message(message_id=1, date=datetime.now(timezone.utc), from_user=USER, text=text,
                          chat=Chat(id=200, type=chat_type)).as_(self.bot)
        name, _, args = text.lstrip('/').partition(' ')
        return message, CommandObject(prefix='/', command=name, args=args or None)

    async def test_pay_sends_topup_invoice(self) -> None:
        for text, stars in (('/pay', SUBSCRIPTION_SETTINGS.TOPUP_STARS), ('/pay 500', 500)):
            with self.subTest(text=text):
                await cmd_pay(*self.command(text))
                invoice = self.sent()
                self.assertEqual((invoice.payload, invoice.currency, invoice.prices[0].amount),
                                 (TOPUP_PAYLOAD, 'XTR', stars))
                self.assertIsNone(getattr(invoice, 'subscription_period', None))

    async def test_pay_rejects_bad_amounts_and_groups(self) -> None:
        for text, chat_type in (('/pay 0', 'private'), ('/pay 10001', 'private'), ('/pay abc', 'private'),
                                ('/pay -5', 'private'), ('/pay', 'group')):
            with self.subTest(text=text, chat_type=chat_type):
                await cmd_pay(*self.command(text, chat_type))
                self.assertFalse(hasattr(self.sent(), 'prices'))

    async def test_balance_reports_stored_credits(self) -> None:
        await self.chat_data.save(200, ConversationInfo(credits=42))
        await cmd_balance(*self.command('/balance'))
        self.assertIn('42 credits', self.sent().text)

    def as_admin(self, admin: bool = True):
        return patch('kibernikto.telegram.handlers.payments.is_from_admin', return_value=admin)

    async def test_admin_pay_adjusts_target_without_invoice(self) -> None:
        await self.chat_data.save(777, ConversationInfo(credits=10))
        with self.as_admin():
            await cmd_pay(*self.command('/pay 100 777', chat_type='group'))
            self.assertIn('Balance: 110', self.sent().text)
            await cmd_pay(*self.command('/pay -500 777'))
        self.assertEqual((await self.chat_data.load(777)).credits, 0)
        self.assertFalse(hasattr(self.sent(), 'prices'))

    async def test_admin_pay_rejects_garbage(self) -> None:
        with self.as_admin():
            for text in ('/pay 0 777', '/pay abc 777', '/pay 10 bob'):
                with self.subTest(text=text):
                    await cmd_pay(*self.command(text))
                    self.assertIn('Usage', self.sent().text)
        self.assertEqual(self.chat_data.rows, {})

    async def test_non_admin_cannot_touch_others(self) -> None:
        with self.as_admin(False):
            await cmd_pay(*self.command('/pay 100 777'))
            self.assertIn('Only admins', self.sent().text)
            await cmd_balance(*self.command('/balance 777'))
            self.assertIn('Only admins', self.sent().text)
        self.assertEqual(self.chat_data.rows, {})

    async def test_admin_commands_switch_disables_admin_args(self) -> None:
        with self.as_admin(), patch.object(TELEGRAM_SETTINGS, 'ADMIN_COMMANDS_ALLOWED', False):
            await cmd_pay(*self.command('/pay 100 777'))
        self.assertIn('Only admins', self.sent().text)

    async def test_admin_balance_reads_target(self) -> None:
        await self.chat_data.save(777, ConversationInfo(credits=9))
        with self.as_admin():
            await cmd_balance(*self.command('/balance 777'))
            self.assertIn('Chat 777: 9 credits', self.sent().text)
            await cmd_balance(*self.command('/balance bob'))
            self.assertIn('Usage', self.sent().text)