import hashlib
import hmac
import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from merchants.models import APIKey, Merchant
from webhooks.models import WebhookEndpoint, WebhookEvent
from webhooks.webhook_service import WebhookService


class WebhookEndpointModelTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name='Webhook Model Corp',
            email='webhookmodel@test.com',
            phone='9000000020',
        )
        self.endpoint = WebhookEndpoint.objects.create(
            merchant=self.merchant,
            url='https://example.com/webhook',
            event_types=['payment.captured', 'refund.processed'],
            secret='test_secret_abc123',
        )

    def test_endpoint_created_with_uuid(self):
        self.assertIsNotNone(self.endpoint.id)

    def test_sign_payload_returns_hmac(self):
        payload = '{"event":"payment.captured"}'
        signature = self.endpoint.sign_payload(payload)
        expected = hmac.new(
            b'test_secret_abc123',
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(signature, expected)

    def test_sign_payload_different_secrets_differ(self):
        endpoint2 = WebhookEndpoint.objects.create(
            merchant=self.merchant,
            url='https://example.com/webhook2',
            event_types=['payment.captured'],
            secret='different_secret',
        )
        payload = '{"event":"test"}'
        self.assertNotEqual(
            self.endpoint.sign_payload(payload),
            endpoint2.sign_payload(payload)
        )

    def test_webhook_event_created(self):
        event = WebhookEvent.objects.create(
            endpoint=self.endpoint,
            event_type='payment.captured',
            payload={'amount': 50000},
            status='pending',
        )
        self.assertEqual(event.status, 'pending')
        self.assertEqual(event.attempts, 0)


class WebhookServiceTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name='Webhook Service Corp',
            email='webhookservice@test.com',
            phone='9000000021',
        )
        self.endpoint = WebhookEndpoint.objects.create(
            merchant=self.merchant,
            url='https://example.com/webhook',
            event_types=['payment.captured', 'refund.processed'],
            secret='service_secret_xyz',
        )
        self.service = WebhookService()

    @patch('webhooks.webhook_service.requests.post')
    def test_successful_delivery(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            text='OK'
        )
        event = WebhookEvent.objects.create(
            endpoint=self.endpoint,
            event_type='payment.captured',
            payload={'payment_id': 'pay_123', 'amount': 50000},
            status='pending',
        )
        self.service._attempt_delivery(event)
        event.refresh_from_db()
        self.assertEqual(event.status, 'delivered')
        self.assertEqual(event.attempts, 1)
        self.assertEqual(event.response_status, 200)

    @patch('webhooks.webhook_service.requests.post')
    def test_failed_delivery_schedules_retry(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=500,
            text='Internal Server Error'
        )
        event = WebhookEvent.objects.create(
            endpoint=self.endpoint,
            event_type='payment.captured',
            payload={'payment_id': 'pay_456'},
            status='pending',
        )
        self.service._attempt_delivery(event)
        event.refresh_from_db()
        self.assertEqual(event.status, 'failed')
        self.assertEqual(event.attempts, 1)
        self.assertIsNotNone(event.next_retry_at)

    @patch('webhooks.webhook_service.requests.post')
    def test_dead_letter_after_max_attempts(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=500,
            text='Error'
        )
        event = WebhookEvent.objects.create(
            endpoint=self.endpoint,
            event_type='payment.captured',
            payload={'payment_id': 'pay_789'},
            status='failed',
            attempts=5,  # Already tried 5 times
        )
        self.service._attempt_delivery(event)
        event.refresh_from_db()
        self.assertEqual(event.status, 'dead_letter')
        self.assertIsNone(event.next_retry_at)

    @patch('webhooks.webhook_service.requests.post')
    def test_timeout_marks_as_failed(self, mock_post):
        import requests as req
        mock_post.side_effect = req.exceptions.Timeout()
        event = WebhookEvent.objects.create(
            endpoint=self.endpoint,
            event_type='payment.captured',
            payload={'payment_id': 'pay_timeout'},
            status='pending',
        )
        self.service._attempt_delivery(event)
        event.refresh_from_db()
        self.assertEqual(event.status, 'failed')
        self.assertIn('timed out', event.failure_reason.lower())

    @patch('webhooks.webhook_service.requests.post')
    def test_signature_header_sent(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, text='OK')
        event = WebhookEvent.objects.create(
            endpoint=self.endpoint,
            event_type='payment.captured',
            payload={'amount': 50000},
            status='pending',
        )
        self.service._attempt_delivery(event)
        call_kwargs = mock_post.call_args
        headers = call_kwargs[1]['headers']
        self.assertIn('X-PayZap-Signature', headers)
        self.assertTrue(headers['X-PayZap-Signature'].startswith('sha256='))

    @patch('webhooks.webhook_service.requests.post')
    def test_dispatch_only_sends_to_subscribed_endpoints(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, text='OK')

        # Endpoint subscribed to payment.captured
        subscribed = WebhookEndpoint.objects.create(
            merchant=self.merchant,
            url='https://example.com/subscribed',
            event_types=['payment.captured'],
            secret='secret1',
        )

        # Endpoint NOT subscribed to this event
        WebhookEndpoint.objects.create(
            merchant=self.merchant,
            url='https://example.com/not-subscribed',
            event_types=['refund.processed'],
            secret='secret2',
        )

        # Deactivate the original endpoint so only our two above count
        self.endpoint.is_active = False
        self.endpoint.save()

        self.service.dispatch_event(
            self.merchant,
            'payment.captured',
            {'payment_id': 'pay_dispatch'}
        )

        # Only 1 event created — for the subscribed endpoint
        events = WebhookEvent.objects.filter(event_type='payment.captured')
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().endpoint, subscribed)

    @patch('webhooks.webhook_service.requests.post')
    def test_retry_pending_delivers_due_events(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, text='OK')
        from datetime import timedelta

        # Event that is due for retry
        due_event = WebhookEvent.objects.create(
            endpoint=self.endpoint,
            event_type='payment.captured',
            payload={'payment_id': 'pay_retry'},
            status='failed',
            attempts=1,
            next_retry_at=timezone.now() - timedelta(minutes=1),
        )

        # Event not yet due
        future_event = WebhookEvent.objects.create(
            endpoint=self.endpoint,
            event_type='payment.captured',
            payload={'payment_id': 'pay_future'},
            status='failed',
            attempts=1,
            next_retry_at=timezone.now() + timedelta(hours=1),
        )

        self.service.retry_pending()

        due_event.refresh_from_db()
        future_event.refresh_from_db()

        self.assertEqual(due_event.status, 'delivered')
        self.assertEqual(future_event.status, 'failed')  # untouched


class WebhookAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'Webhook API Corp {unique}',
            email=f'webhookapi_{unique}@test.com',
            phone='9000000022',
        )
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'webhooks': True},
        )
        self.api_key = full_key

    def test_create_webhook_returns_201(self):
        response = self.client.post(
            '/v1/webhooks/create/',
            {
                'url': 'https://example.com/webhook',
                'event_types': ['payment.captured'],
            },
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn('secret', response.data)
        self.assertIn('id', response.data)

    def test_create_webhook_missing_url_returns_400(self):
        response = self.client.post(
            '/v1/webhooks/create/',
            {'event_types': ['payment.captured']},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)

    def test_create_webhook_empty_event_types_returns_400(self):
        response = self.client.post(
            '/v1/webhooks/create/',
            {'url': 'https://example.com/wh', 'event_types': []},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)

    def test_list_webhooks_returns_200(self):
        WebhookEndpoint.objects.create(
            merchant=self.merchant,
            url='https://example.com/wh1',
            event_types=['payment.captured'],
            secret='sec1',
        )
        response = self.client.get(
            '/v1/webhooks/',
            **{'HTTP_X_API_KEY': self.api_key}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['webhooks']), 1)

    def test_unauthenticated_returns_401(self):
        response = self.client.post(
            '/v1/webhooks/create/',
            {'url': 'https://example.com/wh', 'event_types': ['payment.captured']},
            format='json'
        )
        self.assertEqual(response.status_code, 401)

    @patch('webhooks.webhook_service.requests.post')
    def test_webhook_test_endpoint(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, text='OK')
        endpoint = WebhookEndpoint.objects.create(
            merchant=self.merchant,
            url='https://example.com/test-wh',
            event_types=['payment.captured'],
            secret='test_sec',
        )
        response = self.client.post(
            f'/v1/webhooks/{endpoint.id}/test/',
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'delivered')
        self.assertEqual(response.data['attempts'], 1)
