import pytest
from rest_framework.test import APIClient
from tests.factories import MerchantFactory, APIKeyFactory, OrderFactory, PaymentFactory
from payments.models import Payment, Refund


@pytest.mark.django_db
class TestRefundReconciliation:

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory()
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_full_refund(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        payment = PaymentFactory(
            order=order,
            amount=100000,
            status='captured',
        )
        resp = self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 100000,
            'reason': 'customer_request',
        }, format='json')
        assert resp.status_code == 201
        payment.refresh_from_db()
        assert payment.status == 'refunded'

    def test_partial_refund(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        payment = PaymentFactory(
            order=order,
            amount=100000,
            status='captured',
        )
        resp = self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 40000,
            'reason': 'partial_return',
        }, format='json')
        assert resp.status_code == 201
        payment.refresh_from_db()
        assert payment.status == 'partially_refunded'

    def test_two_partial_refunds_equal_full(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        payment = PaymentFactory(
            order=order,
            amount=100000,
            status='captured',
        )
        self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 40000,
            'reason': 'partial_return',
        }, format='json')

        self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 60000,
            'reason': 'partial_return',
        }, format='json')

        payment.refresh_from_db()
        assert payment.status == 'refunded'
        total_refunded = sum(
            r.amount for r in payment.refunds.filter(status='processed')
        )
        assert total_refunded == 100000

    def test_refund_exceeds_captured_amount_returns_400(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        payment = PaymentFactory(
            order=order,
            amount=100000,
            status='captured',
        )
        resp = self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 150000,
            'reason': 'test',
        }, format='json')
        assert resp.status_code == 400

    def test_refund_uncaptured_payment_returns_400(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        payment = PaymentFactory(
            order=order,
            amount=100000,
            status='authorized',
        )
        resp = self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 100000,
            'reason': 'test',
        }, format='json')
        assert resp.status_code == 400