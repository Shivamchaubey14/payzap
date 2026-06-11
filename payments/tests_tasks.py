import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from merchants.models import Merchant
from payments.models import Order, Payment
from payments.tasks import expire_stale_orders, send_payment_confirmation_email


class ExpireStaleOrdersTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name='Task Test Corp',
            email='tasks@test.com',
            phone='9000000005',
        )

    def test_expires_old_created_orders(self):
        order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
            expires_at=timezone.now() - timedelta(minutes=1),
            status='created',
        )
        expire_stale_orders()
        order.refresh_from_db()
        self.assertEqual(order.status, 'expired')

    def test_does_not_expire_paid_orders(self):
        order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
            expires_at=timezone.now() - timedelta(minutes=1),
            status='paid',
        )
        expire_stale_orders()
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')

    def test_does_not_expire_future_orders(self):
        order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
            expires_at=timezone.now() + timedelta(hours=1),
            status='created',
        )
        expire_stale_orders()
        order.refresh_from_db()
        self.assertEqual(order.status, 'created')


class SendConfirmationEmailTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name='Email Test Corp',
            email='email@test.com',
            phone='9000000006',
        )
        self.order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )
        self.payment = Payment.objects.create(
            order=self.order,
            method='card',
            amount=50000,
            status='captured',
            gateway_txn_id='mock_txn_123',
        )

    @patch('payments.tasks.send_mail')
    def test_confirmation_email_sent(self, mock_send_mail):
        send_payment_confirmation_email(str(self.payment.id))
        self.assertTrue(mock_send_mail.called)
        call_args = mock_send_mail.call_args
        self.assertIn('500.00', call_args[1]['subject'])

    @patch('payments.tasks.send_mail')
    def test_email_contains_payment_id(self, mock_send_mail):
        send_payment_confirmation_email(str(self.payment.id))
        call_args = mock_send_mail.call_args
        self.assertIn(str(self.payment.id), call_args[1]['message'])
