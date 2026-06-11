import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

from tests.factories import MerchantFactory
from webhooks.models import WebhookEndpoint, WebhookEvent
from webhooks.webhook_service import WebhookService


@pytest.mark.django_db
class TestWebhookDelivery:

    def setup_method(self):
        self.merchant = MerchantFactory()
        self.endpoint = WebhookEndpoint.objects.create(
            merchant=self.merchant,
            url='https://webhook.test/endpoint',
            event_types=['payment.captured', 'refund.processed'],
            secret='testsecret123',
            is_active=True,
        )
        self.service = WebhookService()

    def test_webhook_delivered_on_200_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = 'OK'

        with patch('webhooks.webhook_service.requests.post', return_value=mock_resp):
            self.service.dispatch_event(
                self.merchant,
                'payment.captured',
                {'payment_id': 'test_123', 'amount': 50000},
            )

        event = WebhookEvent.objects.filter(
            endpoint=self.endpoint,
            event_type='payment.captured',
        ).first()

        assert event is not None
        assert event.status == 'delivered'
        assert event.attempts == 1
        assert event.response_status == 200

    def test_webhook_failed_on_500_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = 'Internal Server Error'

        with patch('webhooks.webhook_service.requests.post', return_value=mock_resp):
            self.service.dispatch_event(
                self.merchant,
                'payment.captured',
                {'payment_id': 'test_456'},
            )

        event = WebhookEvent.objects.filter(
            endpoint=self.endpoint,
            event_type='payment.captured',
        ).first()

        assert event.status == 'failed'
        assert event.attempts == 1

    def test_webhook_dead_lettered_after_max_attempts(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = 'Error'

        event = WebhookEvent.objects.create(
            endpoint=self.endpoint,
            event_type='payment.captured',
            payload={'test': True},
            status='failed',
            attempts=5,
        )

        with patch('webhooks.webhook_service.requests.post', return_value=mock_resp):
            self.service._attempt_delivery(event)

        event.refresh_from_db()
        assert event.status == 'dead_letter'

    def test_hmac_signature_is_valid(self):
        payload = {'payment_id': 'test_789', 'amount': 50000}
        payload_str = json.dumps(payload, separators=(',', ':'), sort_keys=True)

        signature = self.service._sign('testsecret123', payload_str)

        expected = hmac.new(
            b'testsecret123',
            payload_str.encode(),
            hashlib.sha256,
        ).hexdigest()

        assert signature == expected

    def test_unsubscribed_event_not_delivered(self):
        with patch('webhooks.webhook_service.requests.post') as mock_post:
            self.service.dispatch_event(
                self.merchant,
                'settlement.processed',
                {'settlement_id': 'stl_001'},
            )
            mock_post.assert_not_called()

    def test_inactive_endpoint_not_delivered(self):
        self.endpoint.is_active = False
        self.endpoint.save()

        with patch('webhooks.webhook_service.requests.post') as mock_post:
            self.service.dispatch_event(
                self.merchant,
                'payment.captured',
                {'payment_id': 'test_000'},
            )
            mock_post.assert_not_called()
