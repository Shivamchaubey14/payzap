import pytest
from rest_framework.test import APIClient

from tests.factories import APIKeyFactory, MerchantFactory, OrderFactory, PaymentFactory


@pytest.mark.django_db
class TestPaymentCapture:

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory()
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_capture_authorized_payment(self):
        order = OrderFactory(merchant=self.merchant)
        payment = PaymentFactory(
            order=order,
            status='authorized',
            amount=50000,
        )
        resp = self.client.post(f'/v1/payments/{payment.id}/capture/')
        assert resp.status_code == 200
        payment.refresh_from_db()
        assert payment.status == 'captured'

    def test_capture_already_captured_returns_400(self):
        order = OrderFactory(merchant=self.merchant)
        payment = PaymentFactory(order=order, status='captured')
        resp = self.client.post(f'/v1/payments/{payment.id}/capture/')
        assert resp.status_code == 400

    def test_capture_failed_payment_returns_400(self):
        order = OrderFactory(merchant=self.merchant)
        payment = PaymentFactory(order=order, status='failed')
        resp = self.client.post(f'/v1/payments/{payment.id}/capture/')
        assert resp.status_code == 400

    def test_get_payment_detail(self):
        order = OrderFactory(merchant=self.merchant)
        payment = PaymentFactory(order=order, status='captured')
        resp = self.client.get(f'/v1/payments/{payment.id}/')
        assert resp.status_code == 200
        assert str(resp.data['id']) == str(payment.id)

    def test_get_payment_wrong_merchant_returns_403(self):
        other_merchant = MerchantFactory()
        order = OrderFactory(merchant=other_merchant)
        payment = PaymentFactory(order=order, status='captured')

        resp = self.client.get(f'/v1/payments/{payment.id}/')
        assert resp.status_code in [403, 404]


@pytest.mark.django_db
class TestPaymentMethods:

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory()
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_card_payment_success_card_number(self):
        order = OrderFactory(merchant=self.merchant)
        payment = PaymentFactory(
            order=order,
            method='card',
            status='captured',
        )
        assert payment.status == 'captured'
        assert payment.method == 'card'

    def test_upi_payment_method_stored(self):
        order = OrderFactory(merchant=self.merchant)
        payment = PaymentFactory(order=order, method='upi', status='captured')
        assert payment.method == 'upi'

    def test_netbanking_payment_method_stored(self):
        order = OrderFactory(merchant=self.merchant)
        payment = PaymentFactory(order=order, method='netbanking', status='captured')
        assert payment.method == 'netbanking'

    def test_wallet_payment_method_stored(self):
        order = OrderFactory(merchant=self.merchant)
        payment = PaymentFactory(order=order, method='wallet', status='captured')
        assert payment.method == 'wallet'
