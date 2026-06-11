import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from merchants.models import Merchant
from payments.models import Order, Payment


class EndToEndPaymentFlowTest(TestCase):
    """
    Full end-to-end test covering the complete payment flow:
    Register → Get API Key → Create Order → Process Payment →
    Verify DB State → Capture → Verify Settled
    """

    def setUp(self):
        self.client = APIClient()

    def _unique_email(self, base):
        return f"{base}_{uuid.uuid4().hex[:6]}@test.com"

    def _register(self, name, phone):
        """Helper — registers a merchant and returns (api_key, merchant_id)."""
        response = self.client.post('/v1/accounts/register/', {
            'business_name': name,
            'email': self._unique_email(name.lower().replace(' ', '_')),
            'phone': phone,
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123',
        }, format='json')
        self.assertEqual(response.status_code, 201, f"Registration failed: {response.data}")
        return response.data['test_api_key'], response.data['merchant_id']

    def test_full_payment_flow_success(self):
        # Step 1 — Register merchant
        api_key, merchant_id = self._register('E2E Test Corp', '9000000010')
        self.assertTrue(api_key.startswith('rzp_test_'))

        # Step 2 — Create order
        order_response = self.client.post('/v1/orders/create/', {
            'amount': 100000,
            'currency': 'INR',
            'receipt': 'e2e_receipt_001',
        }, format='json', HTTP_X_API_KEY=api_key)

        self.assertEqual(order_response.status_code, 201)
        order_id = order_response.data['id']
        self.assertEqual(order_response.data['status'], 'created')
        self.assertEqual(order_response.data['amount_in_rupees'], 1000.0)

        # Step 3 — Process payment with success card
        payment_response = self.client.post('/v1/payments/', {
            'order_id': order_id,
            'method': 'card',
            'card_number': '4111111111111111',
        }, format='json', HTTP_X_API_KEY=api_key)

        self.assertEqual(payment_response.status_code, 201)
        payment_id = payment_response.data['id']
        self.assertEqual(payment_response.data['status'], 'authorized')

        # Step 4 — Verify DB state
        payment = Payment.objects.get(id=payment_id)
        self.assertEqual(payment.status, 'authorized')
        self.assertTrue(payment.gateway_txn_id.startswith('mock_auth_'))

        order = Order.objects.get(id=order_id)
        self.assertEqual(order.status, 'attempted')

        # Step 5 — Capture payment
        capture_response = self.client.post(
            f'/v1/payments/{payment_id}/capture/',
            format='json',
            HTTP_X_API_KEY=api_key
        )
        self.assertEqual(capture_response.status_code, 200)
        self.assertEqual(capture_response.data['status'], 'captured')

        # Step 6 — Verify final DB state
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'captured')
        self.assertIsNotNone(payment.captured_at)

        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')

    def test_full_payment_flow_declined(self):
        api_key, _ = self._register('Decline Test Corp', '9000000011')

        order_response = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
        }, format='json', HTTP_X_API_KEY=api_key)
        self.assertEqual(order_response.status_code, 201)
        order_id = order_response.data['id']

        payment_response = self.client.post('/v1/payments/', {
            'order_id': order_id,
            'method': 'card',
            'card_number': '4000000000000002',
        }, format='json', HTTP_X_API_KEY=api_key)

        self.assertEqual(payment_response.status_code, 201)
        self.assertEqual(payment_response.data['status'], 'failed')

        payment = Payment.objects.get(id=payment_response.data['id'])
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'CARD_DECLINED')

    def test_idempotency_prevents_double_order(self):
        api_key, merchant_id = self._register('Idem Test Corp', '9000000012')
        idem_key = str(uuid.uuid4())

        r1 = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
            'idempotency_key': idem_key,
        }, format='json', HTTP_X_API_KEY=api_key)

        r2 = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
            'idempotency_key': idem_key,
        }, format='json', HTTP_X_API_KEY=api_key)

        self.assertEqual(r1.data['id'], r2.data['id'])
        merchant = Merchant.objects.get(id=merchant_id)
        self.assertEqual(Order.objects.filter(merchant=merchant).count(), 1)

    def test_ownership_isolation_between_merchants(self):
        key_a, _ = self._register('Merchant A', '9000000013')
        key_b, _ = self._register('Merchant B', '9000000014')

        # Merchant A creates an order
        order_response = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
        }, format='json', HTTP_X_API_KEY=key_a)
        self.assertEqual(order_response.status_code, 201, f"Order creation failed: {order_response.data}")
        order_id = order_response.data['id']

        # Merchant B tries to access merchant A's order — must get 403
        response = self.client.get(
            f'/v1/orders/{order_id}/',
            HTTP_X_API_KEY=key_b
        )
        self.assertEqual(response.status_code, 403)

        # Merchant B tries to pay merchant A's order — must get 404
        payment_response = self.client.post('/v1/payments/', {
            'order_id': order_id,
            'method': 'card',
            'card_number': '4111111111111111',
        }, format='json', HTTP_X_API_KEY=key_b)
        self.assertEqual(payment_response.status_code, 404)
