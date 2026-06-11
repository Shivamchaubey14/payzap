import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from merchants.models import APIKey, Merchant
from payments.models import Order, Payment
from payments.processors.mock_gateway import MockBankGateway
from payments.services import PaymentService


class MockGatewayTest(TestCase):

    def setUp(self):
        self.gateway = MockBankGateway()
        self.gateway.PROCESSING_DELAY = 0  # No delay in tests
        self.merchant = Merchant.objects.create(
            business_name='Gateway Test Corp',
            email='gateway@test.com',
            phone='9000000002',
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
        )

    def test_success_card_returns_authorized(self):
        result = self.gateway.authorize(
            self.payment,
            {'card_number': '4111111111111111'}
        )
        self.assertTrue(result.success)
        self.assertEqual(result.status, 'authorized')
        self.assertTrue(result.gateway_txn_id.startswith('mock_auth_'))

    def test_decline_card_returns_failed(self):
        result = self.gateway.authorize(
            self.payment,
            {'card_number': '4000000000000002'}
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.error_code, 'CARD_DECLINED')

    def test_3ds_card_returns_pending_3ds(self):
        result = self.gateway.authorize(
            self.payment,
            {'card_number': '4000000000003220'}
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, 'pending_3ds')
        self.assertEqual(result.error_code, '3DS_REQUIRED')

    def test_timeout_card_returns_failed(self):
        result = self.gateway.authorize(
            self.payment,
            {'card_number': '4000000000000119'}
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, 'GATEWAY_TIMEOUT')

    def test_capture_authorized_payment(self):
        self.payment.status = 'authorized'
        self.payment.save()
        result = self.gateway.capture(self.payment, 50000)
        self.assertTrue(result.success)
        self.assertEqual(result.status, 'captured')

    def test_capture_wrong_state_returns_failed(self):
        result = self.gateway.capture(self.payment, 50000)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, 'INVALID_STATE')

    def test_refund_captured_payment(self):
        self.payment.status = 'captured'
        self.payment.save()
        result = self.gateway.refund(self.payment, 50000)
        self.assertTrue(result.success)
        self.assertEqual(result.status, 'refunded')

    def test_refund_exceeds_amount_returns_failed(self):
        self.payment.status = 'captured'
        self.payment.save()
        result = self.gateway.refund(self.payment, 99999999)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, 'REFUND_AMOUNT_EXCEEDS_CAPTURED')


class PaymentServiceTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.merchant = Merchant.objects.create(
            business_name='Service Test Corp',
            email='service@test.com',
            phone='9000000003',
        )

    def setUp(self):
        self.service = PaymentService()
        self.service.gateway.PROCESSING_DELAY = 0
        self.order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )

    def test_process_payment_success(self):
        payment = self.service.process_payment(
            self.order,
            {'method': 'card', 'card_number': '4111111111111111'}
        )
        self.assertEqual(payment.status, 'authorized')
        self.assertTrue(payment.gateway_txn_id.startswith('mock_auth_'))

    def test_process_payment_decline(self):
        payment = self.service.process_payment(
            self.order,
            {'method': 'card', 'card_number': '4000000000000002'}
        )
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'CARD_DECLINED')

    def test_order_status_updated_to_attempted(self):
        self.service.process_payment(
            self.order,
            {'method': 'card', 'card_number': '4111111111111111'}
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'attempted')

    def test_paid_order_cannot_be_processed_again(self):
        self.order.status = 'paid'
        self.order.save()
        with self.assertRaises(ValueError):
            self.service.process_payment(
                self.order,
                {'method': 'card', 'card_number': '4111111111111111'}
            )

    def test_capture_authorized_payment(self):
        payment = self.service.process_payment(
            self.order,
            {'method': 'card', 'card_number': '4111111111111111'}
        )
        captured = self.service.capture_payment(payment)
        self.assertEqual(captured.status, 'captured')
        self.assertIsNotNone(captured.captured_at)

    def test_capture_updates_order_to_paid(self):
        payment = self.service.process_payment(
            self.order,
            {'method': 'card', 'card_number': '4111111111111111'}
        )
        self.service.capture_payment(payment)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')


class PaymentAPITest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.merchant = Merchant.objects.create(
            business_name='Payment API Corp',
            email='payapi@test.com',
            phone='9000000004',
        )
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=cls.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'payments': True},
        )
        cls.api_key = full_key

    def setUp(self):
        self.client = APIClient()
        self.order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )

    def test_process_payment_returns_201(self):
        response = self.client.post(
            '/v1/payments/',
            {
                'order_id': str(self.order.id),
                'method': 'card',
                'card_number': '4111111111111111',
            },
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'authorized')

    def test_declined_card_returns_201_with_failed_status(self):
        response = self.client.post(
            '/v1/payments/',
            {
                'order_id': str(self.order.id),
                'method': 'card',
                'card_number': '4000000000000002',
            },
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'failed')

    def test_invalid_order_id_returns_404(self):
        response = self.client.post(
            '/v1/payments/',
            {
                'order_id': str(uuid.uuid4()),
                'method': 'card',
                'card_number': '4111111111111111',
            },
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 404)

    def test_get_payment_returns_200(self):
        payment = Payment.objects.create(
            order=self.order,
            method='card',
            amount=50000,
            status='authorized',
        )
        response = self.client.get(
            f'/v1/payments/{payment.id}/',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'authorized')

    def test_unauthenticated_returns_401(self):
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(self.order.id), 'method': 'card'},
            format='json'
        )
        self.assertEqual(response.status_code, 401)
