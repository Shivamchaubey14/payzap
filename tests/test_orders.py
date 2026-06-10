import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from tests.factories import MerchantFactory, APIKeyFactory


@pytest.mark.django_db
class TestOrderCreation:

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory()
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_create_order_success(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
            'receipt': 'rcpt_001',
        }, format='json')
        assert resp.status_code == 201
        assert resp.data['amount'] == 50000
        assert resp.data['currency'] == 'INR'
        assert resp.data['status'] == 'created'

    def test_create_order_missing_amount(self):
        resp = self.client.post('/v1/orders/create/', {
            'currency': 'INR',
        }, format='json')
        assert resp.status_code == 400

    def test_create_order_zero_amount(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': 0,
            'currency': 'INR',
        }, format='json')
        assert resp.status_code == 400

    def test_create_order_negative_amount(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': -100,
            'currency': 'INR',
        }, format='json')
        assert resp.status_code == 400

    def test_idempotency_same_key_returns_same_response(self):
        payload = {'amount': 50000, 'currency': 'INR', 'receipt': 'rcpt_idem'}
        resp1 = self.client.post(
    '/v1/orders/create/',
            payload,
            format='json',
            HTTP_IDEMPOTENCY_KEY='test-idem-key-001'
        )
        resp2 = self.client.post(
            '/v1/orders/create/',
            payload,
            format='json',
            HTTP_IDEMPOTENCY_KEY='test-idem-key-001'
        )
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        import json
        assert resp1.json()['id'] == resp2.json()['id']

    def test_get_order_success(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
        }, format='json')
        order_id = resp.data['id']
        get_resp = self.client.get(f'/v1/orders/{order_id}/')
        assert get_resp.status_code == 200
        assert get_resp.data['id'] == order_id

    def test_get_order_wrong_merchant_returns_403(self):
        resp = self.client.post('/v1/orders/create/', {
            'amount': 50000,
            'currency': 'INR',
        }, format='json')
        order_id = resp.data['id']

        other_merchant = MerchantFactory()
        other_key = APIKeyFactory(merchant=other_merchant)
        other_client = APIClient()
        other_client.credentials(HTTP_X_API_KEY=other_key.full_key)

        get_resp = other_client.get(f'/v1/orders/{order_id}/')
        assert get_resp.status_code in [403, 404]

    def test_unauthenticated_request_returns_401(self):
        unauth_client = APIClient()
        resp = unauth_client.post('/v1/orders/', {
            'amount': 50000,
            'currency': 'INR',
        }, format='json')
        assert resp.status_code == 401