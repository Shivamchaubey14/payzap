import hmac
import hashlib
import json
import logging
import requests
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# Retry schedule in seconds: 0, 5min, 30min, 2hr, 8hr, 24hr
RETRY_DELAYS = [0, 300, 1800, 7200, 28800, 86400]


@shared_task(bind=True, max_retries=6, name='webhooks.deliver_webhook')
def deliver_webhook(self, webhook_event_id: str):
    """
    Deliver a webhook event to the merchant's endpoint.
    Retries up to 6 times with exponential backoff.
    On all retries exhausted, moves to dead-letter queue.
    """
    from webhooks.models import WebhookEndpoint, WebhookEvent

    try:
        event = WebhookEvent.objects.select_related('webhook').get(id=webhook_event_id)
    except WebhookEvent.DoesNotExist:
        logger.error(f"WebhookEvent {webhook_event_id} not found")
        return

    webhook = event.webhook

    if not webhook.is_active:
        logger.info(f"Webhook {webhook.id} is inactive — skipping delivery")
        return

    # Build payload
    payload = json.dumps(event.payload, separators=(',', ':'))

    # Generate HMAC-SHA256 signature
    # Merchant verifies this to confirm the webhook came from PayZap
    secret = webhook.secret_hash.encode()
    signature = 'sha256=' + hmac.new(
        secret, payload.encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        'Content-Type': 'application/json',
        'X-PayZap-Signature': signature,
        'X-PayZap-Event': event.event_type,
        'X-PayZap-Delivery': str(event.id),
    }

    # Update attempt count
    event.attempts += 1
    event.last_attempt_at = timezone.now()

    try:
        response = requests.post(
            webhook.url,
            data=payload,
            headers=headers,
            timeout=10,  # 10 second timeout per attempt
        )

        event.response_status_code = response.status_code
        event.response_body = response.text[:2000]  # Store first 2KB

        if response.status_code in (200, 201, 202, 204):
            event.status = 'delivered'
            event.save()
            logger.info(f"Webhook {event.id} delivered successfully ({response.status_code})")
            return

        # Non-2xx — treat as failure, retry
        raise Exception(f"Non-2xx response: {response.status_code}")

    except Exception as exc:
        event.status = 'failed'
        event.save()

        retry_number = self.request.retries
        logger.warning(
            f"Webhook {event.id} delivery failed "
            f"(attempt {event.attempts}/6): {exc}"
        )

        if retry_number < self.max_retries:
            delay = RETRY_DELAYS[min(retry_number + 1, len(RETRY_DELAYS) - 1)]
            event.next_retry_at = timezone.now() + timezone.timedelta(seconds=delay)
            event.save()
            raise self.retry(exc=exc, countdown=delay)
        else:
            # All 6 retries exhausted — dead letter queue
            event.status = 'dead_letter'
            event.save()
            logger.error(
                f"Webhook {event.id} moved to dead-letter queue "
                f"after 6 failed attempts"
            )


@shared_task(name='webhooks.dispatch_event')
def dispatch_webhook_event(merchant_id: str, event_type: str, payload: dict):
    """
    Finds all active webhook endpoints for a merchant that subscribe
    to this event type, creates WebhookEvent records, and queues delivery.
    Called after every payment state change.
    """
    from webhooks.models import WebhookEndpoint, WebhookEvent
    import uuid

    endpoints = WebhookEndpoint.objects.filter(
        merchant_id=merchant_id,
        is_active=True,
    )

    for endpoint in endpoints:
        # Check if this endpoint subscribes to this event type
        if event_type not in endpoint.event_types and '*' not in endpoint.event_types:
            continue

        event = WebhookEvent.objects.create(
            webhook=endpoint,
            event_type=event_type,
            payload={
                'id': f"evt_{uuid.uuid4().hex[:16]}",
                'event': event_type,
                'created_at': timezone.now().isoformat(),
                'data': payload,
            },
            status='pending',
        )

        # Queue delivery immediately
        deliver_webhook.delay(str(event.id))
        logger.info(f"Queued webhook {event.id} for {event_type} to {endpoint.url}")