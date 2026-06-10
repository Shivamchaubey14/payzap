import uuid
from django.test import TestCase
from rest_framework.test import APIClient
from merchants.models import Merchant, APIKey
from payments.models import Order, Payment, Refund
from payments.refund_service import RefundService


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_merchant(prefix='refund'):
    unique = uuid.uuid4().hex[:8]
    return Merchant.objects.create(
        business_name=f'{prefix} Corp {unique}',
        email=f'{prefix}_{unique}@corp.com',
        phone='9500000001',
    )


def make_order(merchant, amount=50000):
    return Order.objects.create(
        merchant=merchant,
        amount=amount,
        currency='INR',
        idempotency_key=str(uuid.uuid4()),
    )


def make_captured_payment(order, amount=50000):
    """Creates a payment already in captured state — skips gateway."""
    return Payment.objects.create(
        order=order,
        method='card',
        amount=amount,
        currency='INR',
        status='captured',
        gateway_txn_id=f'mock_cap_{uuid.uuid4().hex[:12]}',
    )


# ─────────────────────────────────────────────────────────────────────────────
# Refund Model Tests
# ─────────────────────────────────────────────────────────────────────────────

class RefundModelTest(TestCase):

    def setUp(self):
        self.merchant = make_merchant('model')
        self.order = make_order(self.merchant)
        self.payment = make_captured_payment(self.order)

    def test_refund_created_with_uuid(self):
        refund = Refund.objects.create(
            payment=self.payment,
            amount=10000,
            currency='INR',
        )
        self.assertIsNotNone(refund.id)

    def test_default_status_is_initiated(self):
        refund = Refund.objects.create(
            payment=self.payment,
            amount=10000,
        )
        self.assertEqual(refund.status, 'initiated')

    def test_amount_in_rupees_property(self):
        refund = Refund.objects.create(
            payment=self.payment,
            amount=25000,
        )
        self.assertEqual(refund.amount_in_rupees, 250.0)

    def test_refund_str_contains_amount_and_status(self):
        refund = Refund.objects.create(
            payment=self.payment,
            amount=10000,
        )
        self.assertIn('₹', str(refund))
        self.assertIn('initiated', str(refund))


# ─────────────────────────────────────────────────────────────────────────────
# Refund Service Tests
# ─────────────────────────────────────────────────────────────────────────────

class RefundServiceTest(TestCase):

    def setUp(self):
        self.merchant = make_merchant('service')
        self.order = make_order(self.merchant)
        self.payment = make_captured_payment(self.order)
        self.service = RefundService()

    def test_full_refund_returns_processed(self):
        refund = self.service.initiate_refund(self.payment, amount=50000)
        self.assertEqual(refund.status, 'processed')

    def test_partial_refund_returns_processed(self):
        refund = self.service.initiate_refund(self.payment, amount=20000)
        self.assertEqual(refund.status, 'processed')

    def test_partial_refund_sets_payment_to_partially_refunded(self):
        self.service.initiate_refund(self.payment, amount=20000)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'partially_refunded')

    def test_full_refund_sets_payment_to_refunded(self):
        self.service.initiate_refund(self.payment, amount=50000)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'refunded')

    def test_amount_refunded_updated_correctly(self):
        self.service.initiate_refund(self.payment, amount=20000)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount_refunded, 20000)

    def test_two_partial_refunds_reconcile_correctly(self):
        self.service.initiate_refund(self.payment, amount=20000)
        self.payment.refresh_from_db()
        self.service.initiate_refund(self.payment, amount=30000)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount_refunded, 50000)
        self.assertEqual(self.payment.status, 'refunded')

    def test_refund_exceeding_captured_amount_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.service.initiate_refund(self.payment, amount=60000)
        self.assertIn('exceeds', str(ctx.exception))

    def test_refund_on_failed_payment_raises(self):
        self.payment.status = 'failed'
        self.payment.save()
        with self.assertRaises(ValueError) as ctx:
            self.service.initiate_refund(self.payment, amount=10000)
        self.assertIn('cannot be refunded', str(ctx.exception))

    def test_refund_on_created_payment_raises(self):
        self.payment.status = 'created'
        self.payment.save()
        with self.assertRaises(ValueError):
            self.service.initiate_refund(self.payment, amount=10000)

    def test_zero_amount_refund_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.service.initiate_refund(self.payment, amount=0)
        self.assertIn('greater than zero', str(ctx.exception))

    def test_refund_stores_gateway_refund_id(self):
        refund = self.service.initiate_refund(self.payment, amount=10000)
        self.assertTrue(refund.gateway_refund_id.startswith('rfnd_'))

    def test_refund_stores_reason(self):
        refund = self.service.initiate_refund(
            self.payment, amount=10000, reason='Customer request'
        )
        self.assertEqual(refund.reason, 'Customer request')

    def test_refund_processed_at_is_set(self):
        refund = self.service.initiate_refund(self.payment, amount=10000)
        self.assertIsNotNone(refund.processed_at)

    def test_second_refund_exceeding_remaining_raises(self):
        self.service.initiate_refund(self.payment, amount=40000)
        self.payment.refresh_from_db()
        with self.assertRaises(ValueError):
            self.service.initiate_refund(self.payment, amount=20000)

    def test_get_refund_returns_correct_refund(self):
        refund = self.service.initiate_refund(self.payment, amount=10000)
        fetched = self.service.get_refund(str(refund.id), self.merchant)
        self.assertEqual(fetched.id, refund.id)

    def test_get_refund_wrong_merchant_raises(self):
        refund = self.service.initiate_refund(self.payment, amount=10000)
        other = make_merchant('other')
        with self.assertRaises(ValueError):
            self.service.get_refund(str(refund.id), other)

    def test_authorized_payment_is_also_refundable(self):
        self.payment.status = 'authorized'
        self.payment.save()
        refund = self.service.initiate_refund(self.payment, amount=10000)
        self.assertEqual(refund.status, 'processed')


# ─────────────────────────────────────────────────────────────────────────────
# Refund API Tests
# ─────────────────────────────────────────────────────────────────────────────

class RefundAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.merchant = make_merchant('api')
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'payments': True, 'refunds': True},
        )
        self.api_key = full_key
        self.order = make_order(self.merchant)
        self.payment = make_captured_payment(self.order)

    def _post_refund(self, payment_id, amount, reason='Test refund'):
        return self.client.post(
            '/v1/refunds/',
            {'payment_id': str(payment_id), 'amount': amount, 'reason': reason},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )

    def test_partial_refund_returns_201(self):
        response = self._post_refund(self.payment.id, 20000)
        self.assertEqual(response.status_code, 201)

    def test_full_refund_returns_201(self):
        response = self._post_refund(self.payment.id, 50000)
        self.assertEqual(response.status_code, 201)

    def test_refund_response_has_correct_fields(self):
        response = self._post_refund(self.payment.id, 20000)
        self.assertIn('id', response.data)
        self.assertIn('payment_id', response.data)
        self.assertIn('amount', response.data)
        self.assertIn('amount_in_rupees', response.data)
        self.assertIn('status', response.data)
        self.assertIn('gateway_refund_id', response.data)

    def test_refund_status_is_processed(self):
        response = self._post_refund(self.payment.id, 20000)
        self.assertEqual(response.data['status'], 'processed')

    def test_amount_in_rupees_is_correct(self):
        response = self._post_refund(self.payment.id, 20000)
        self.assertEqual(response.data['amount_in_rupees'], 200.0)

    def test_refund_exceeding_amount_returns_400(self):
        response = self._post_refund(self.payment.id, 60000)
        self.assertEqual(response.status_code, 400)

    def test_missing_payment_id_returns_400(self):
        response = self.client.post(
            '/v1/refunds/',
            {'amount': 10000},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_amount_returns_400(self):
        response = self.client.post(
            '/v1/refunds/',
            {'payment_id': str(self.payment.id)},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 400)

    def test_wrong_merchant_payment_returns_404(self):
        other_merchant = make_merchant('wrong')
        other_order = make_order(other_merchant)
        other_payment = make_captured_payment(other_order)
        response = self._post_refund(other_payment.id, 10000)
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_request_returns_401(self):
        response = self.client.post(
            '/v1/refunds/',
            {'payment_id': str(self.payment.id), 'amount': 10000},
            format='json',
        )
        self.assertEqual(response.status_code, 401)

    def test_get_refund_returns_200(self):
        create_response = self._post_refund(self.payment.id, 10000)
        refund_id = create_response.data['id']
        response = self.client.get(
            f'/v1/refunds/{refund_id}/',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data['id']), str(refund_id))

    def test_get_nonexistent_refund_returns_404(self):
        response = self.client.get(
            f'/v1/refunds/{uuid.uuid4()}/',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 404)

    def test_two_partial_refunds_succeed(self):
        r1 = self._post_refund(self.payment.id, 20000)
        self.assertEqual(r1.status_code, 201)
        r2 = self._post_refund(self.payment.id, 30000)
        self.assertEqual(r2.status_code, 201)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount_refunded, 50000)
        self.assertEqual(self.payment.status, 'refunded')

    def test_third_refund_after_full_refund_returns_400(self):
        self._post_refund(self.payment.id, 50000)
        response = self._post_refund(self.payment.id, 10000)
        self.assertEqual(response.status_code, 400)