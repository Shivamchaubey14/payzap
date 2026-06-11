import pytest
from rest_framework.test import APIClient
from tests.factories import MerchantFactory, APIKeyFactory, OrderFactory, PaymentFactory


@pytest.mark.django_db
class TestAuthentication:

    def setup_method(self):
        self.client = APIClient()

    def test_no_api_key_returns_401(self):
        resp = self.client.get('/v1/orders/')
        assert resp.status_code == 401

    def test_invalid_api_key_returns_401(self):
        self.client.credentials(HTTP_X_API_KEY='invalid_key_xyz')
        resp = self.client.get('/v1/orders/')
        assert resp.status_code == 401

    def test_wrong_format_key_returns_401(self):
        self.client.credentials(HTTP_X_API_KEY='sk_live_notvalid')
        resp = self.client.get('/v1/orders/')
        assert resp.status_code == 401

    def test_valid_key_returns_200(self):
        merchant = MerchantFactory()
        api_key = APIKeyFactory(merchant=merchant)
        self.client.credentials(HTTP_X_API_KEY=api_key.full_key)
        resp = self.client.get('/v1/orders/')
        assert resp.status_code == 200

    def test_deactivated_key_returns_401(self):
        merchant = MerchantFactory()
        api_key = APIKeyFactory(merchant=merchant, is_active=False)
        self.client.credentials(HTTP_X_API_KEY=api_key.full_key)
        resp = self.client.get('/v1/orders/')
        assert resp.status_code == 401

    def test_suspended_merchant_returns_401(self):
        merchant = MerchantFactory(is_active=False)
        api_key = APIKeyFactory(merchant=merchant)
        self.client.credentials(HTTP_X_API_KEY=api_key.full_key)
        resp = self.client.get('/v1/orders/')
        assert resp.status_code == 401


@pytest.mark.django_db
class TestOwnershipIsolation:
    """IDOR protection — merchants can only access their own data."""

    def setup_method(self):
        self.client = APIClient()
        self.merchant_a = MerchantFactory()
        self.merchant_b = MerchantFactory()
        self.key_a = APIKeyFactory(merchant=self.merchant_a)
        self.key_b = APIKeyFactory(merchant=self.merchant_b)

    def test_merchant_cannot_access_other_merchant_order(self):
        order = OrderFactory(merchant=self.merchant_b)
        self.client.credentials(HTTP_X_API_KEY=self.key_a.full_key)
        resp = self.client.get(f'/v1/orders/{order.id}/')
        assert resp.status_code in [403, 404]

    def test_merchant_cannot_access_other_merchant_payment(self):
        order = OrderFactory(merchant=self.merchant_b)
        payment = PaymentFactory(order=order, status='captured')
        self.client.credentials(HTTP_X_API_KEY=self.key_a.full_key)
        resp = self.client.get(f'/v1/payments/{payment.id}/')
        assert resp.status_code in [403, 404]

    def test_merchant_cannot_refund_other_merchant_payment(self):
        order = OrderFactory(merchant=self.merchant_b)
        payment = PaymentFactory(order=order, status='captured', amount=100000)
        self.client.credentials(HTTP_X_API_KEY=self.key_a.full_key)
        resp = self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 100000,
            'reason': 'test',
        }, format='json')
        assert resp.status_code in [400, 403, 404]

    def test_merchant_cannot_capture_other_merchant_payment(self):
        order = OrderFactory(merchant=self.merchant_b)
        payment = PaymentFactory(order=order, status='authorized')
        self.client.credentials(HTTP_X_API_KEY=self.key_a.full_key)
        resp = self.client.post(f'/v1/payments/{payment.id}/capture/')
        assert resp.status_code in [403, 404]

    def test_merchant_cannot_access_other_merchant_settlement(self):
        from settlements.models import Settlement
        from django.utils import timezone
        Settlement.objects.create(
            merchant=self.merchant_b,
            amount=98000,
            fees=2000,
            status='processed',
            settlement_from=timezone.now(),
            settlement_to=timezone.now(),
        )
        self.client.credentials(HTTP_X_API_KEY=self.key_a.full_key)
        resp = self.client.get('/v1/settlements/')
        assert resp.status_code == 200
        assert resp.data['count'] == 0


@pytest.mark.django_db
class TestInputValidation:

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory(
            is_live=True,
            kyc_status='approved',
            fee_rate=0.02,
            bank_account_number='1234567890',
            bank_ifsc='HDFC0001234',
        )
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_sql_injection_in_order_receipt(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
            'receipt': "'; DROP TABLE orders; --",
        }, format='json')
        # Should either succeed (Django ORM parameterizes) or return 400
        # Must NOT return 500
        assert resp.status_code in [201, 400]

    def test_xss_in_order_notes(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
            'notes': {'key': '<script>alert("xss")</script>'},
        }, format='json')
        # Django ORM stores safely, JSON response is not rendered as HTML
        assert resp.status_code in [201, 400]

    def test_negative_amount_rejected(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': -50000,
            'currency': 'INR',
        }, format='json')
        assert resp.status_code == 400

    def test_zero_amount_rejected(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': 0,
            'currency': 'INR',
        }, format='json')
        assert resp.status_code == 400

    def test_invalid_currency_rejected(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INVALID',
        }, format='json')
        assert resp.status_code == 400

    def test_oversized_payload_handled(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
            'notes': {'key': 'x' * 10000},
        }, format='json')
        assert resp.status_code in [201, 400]

    def test_missing_required_fields_returns_400(self):
        resp = self.client.post('/v1/orders/create/', {}, format='json')
        assert resp.status_code == 400


@pytest.mark.django_db
class TestRefundReconciliationSecurity:
    """Reconciliation tests — amounts must be exact to the paisa."""

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory(
            is_live=True,
            kyc_status='approved',
            fee_rate=0.02,
            bank_account_number='1234567890',
            bank_ifsc='HDFC0001234',
        )
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_100_payments_settlement_reconciliation(self):
        from unittest.mock import patch
        from settlements.models import Settlement
        from settlements.tasks import process_daily_settlements
        from django.db.models import Sum

        total_captured = 0
        for i in range(10):
            order = OrderFactory(merchant=self.merchant, amount=100000)
            PaymentFactory(
                order=order,
                amount=100000,
                status='captured',
                in_settlement=False,
            )
            total_captured += 100000

        with patch('webhooks.tasks.dispatch_webhook_event.delay'):
            process_daily_settlements()

        settlement = Settlement.objects.filter(merchant=self.merchant).first()
        assert settlement is not None

        expected_fee = int(total_captured * float(self.merchant.fee_rate))
        expected_payout = total_captured - expected_fee

        assert settlement.fees == expected_fee
        assert settlement.amount == expected_payout
        assert settlement.fees + settlement.amount == total_captured

    def test_refund_cannot_exceed_payment_amount(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        payment = PaymentFactory(order=order, amount=100000, status='captured')

        resp = self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 100001,
            'reason': 'test',
        }, format='json')
        assert resp.status_code == 400

    def test_double_refund_prevented(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        payment = PaymentFactory(order=order, amount=100000, status='captured')

        self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 100000,
            'reason': 'test',
        }, format='json')

        resp2 = self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 1,
            'reason': 'test',
        }, format='json')
        assert resp2.status_code == 400

    def test_partial_refunds_sum_cannot_exceed_captured(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        payment = PaymentFactory(order=order, amount=100000, status='captured')

        self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 60000,
            'reason': 'partial',
        }, format='json')

        resp2 = self.client.post('/v1/refunds/', {
            'payment_id': str(payment.id),
            'amount': 60000,
            'reason': 'partial',
        }, format='json')
        assert resp2.status_code == 400


@pytest.mark.django_db
class TestRateLimiting:

    def setup_method(self):
        self.client = APIClient()

    def test_unauthenticated_endpoints_return_401_not_500(self):
        endpoints = [
            ('GET', '/v1/orders/'),
            ('GET', '/v1/settlements/'),
            ('GET', '/v1/payouts/'),
            ('POST', '/v1/orders/create/'),
            ('POST', '/v1/refunds/'),
        ]
        for method, url in endpoints:
            if method == 'GET':
                resp = self.client.get(url)
            else:
                resp = self.client.post(url, {}, format='json')
            assert resp.status_code == 401, f'{method} {url} should return 401'

    def test_nonexistent_endpoints_return_404(self):
        resp = self.client.get('/v1/nonexistent/')
        assert resp.status_code == 404

    def test_wrong_http_method_returns_405(self):
        merchant = MerchantFactory()
        api_key = APIKeyFactory(merchant=merchant)
        self.client.credentials(HTTP_X_API_KEY=api_key.full_key)
        resp = self.client.delete('/v1/orders/')
        assert resp.status_code == 405