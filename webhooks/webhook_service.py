import json
import hmac
import hashlib
import logging
import requests
from datetime import timedelta
from django.utils import timezone
from webhooks.models import WebhookEndpoint, WebhookEvent
from merchants.models import Merchant

logger = logging.getLogger(__name__)

# Retry delay schedule in seconds
RETRY_DELAYS = [0, 300, 1800, 7200, 28800, 86400]  # 0s,5m,30m,2h,8h,24h
MAX_ATTEMPTS = 6
REQUEST_TIMEOUT = 10  # seconds


class WebhookService:

    def dispatch_event(self, merchant: Merchant, event_type: str, payload: dict):
        """
        Find all active endpoints subscribed to this event_type,
        create a WebhookEvent for each, and fire the first attempt.
        """
        endpoints = WebhookEndpoint.objects.filter(
            merchant=merchant,
            is_active=True,
        )

        for endpoint in endpoints:
            if event_type not in (endpoint.event_types or []):
                continue

            event = WebhookEvent.objects.create(
                endpoint=endpoint,
                event_type=event_type,
                payload=payload,
                status='pending',
                next_retry_at=timezone.now(),
            )
            self._attempt_delivery(event)

    def _attempt_delivery(self, event: WebhookEvent):
        """Deliver one event. Updates status and schedules retry on failure."""
        endpoint = event.endpoint
        payload_str = json.dumps(event.payload, separators=(',', ':'), sort_keys=True)
        signature = self._sign(endpoint.secret, payload_str)

        headers = {
            'Content-Type':       'application/json',
            'X-PayZap-Signature': f'sha256={signature}',
            'X-PayZap-Event':     event.event_type,
            'X-PayZap-Delivery':  str(event.id),
        }

        attempt_num = event.attempts + 1
        success = False
        response_status = None
        response_body = ''
        failure_reason = ''

        try:
            resp = requests.post(
                endpoint.url,
                data=payload_str,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response_status = resp.status_code
            response_body   = resp.text[:2000]  # cap at 2KB
            success = 200 <= resp.status_code < 300

        except requests.exceptions.Timeout:
            failure_reason = 'Request timed out.'
        except requests.exceptions.ConnectionError as e:
            failure_reason = f'Connection error: {str(e)[:200]}'
        except Exception as e:
            failure_reason = f'Unexpected error: {str(e)[:200]}'

        now = timezone.now()

        if success:
            WebhookEvent.objects.filter(id=event.id).update(
                status='delivered',
                attempts=attempt_num,
                last_attempt_at=now,
                response_status=response_status,
                response_body=response_body,
                next_retry_at=None,
            )
            logger.info(f"Webhook {event.id} delivered to {endpoint.url}")

        else:
            if attempt_num >= MAX_ATTEMPTS:
                new_status = 'dead_letter'
                next_retry = None
                logger.warning(f"Webhook {event.id} dead-lettered after {attempt_num} attempts")
            else:
                new_status = 'failed'
                delay = RETRY_DELAYS[attempt_num] if attempt_num < len(RETRY_DELAYS) else 86400
                next_retry = now + timedelta(seconds=delay)
                logger.warning(f"Webhook {event.id} failed attempt {attempt_num}, retry at {next_retry}")

            WebhookEvent.objects.filter(id=event.id).update(
                status=new_status,
                attempts=attempt_num,
                last_attempt_at=now,
                response_status=response_status,
                response_body=response_body,
                failure_reason=failure_reason or f'HTTP {response_status}',
                next_retry_at=next_retry,
            )

        event.refresh_from_db()

    def retry_pending(self):
        """
        Called by Celery Beat — picks up all failed events due for retry.
        """
        due_events = WebhookEvent.objects.filter(
            status='failed',
            next_retry_at__lte=timezone.now(),
        ).select_related('endpoint')

        for event in due_events:
            self._attempt_delivery(event)

    def _sign(self, secret: str, payload: str) -> str:
        return hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()