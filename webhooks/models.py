import uuid
import hashlib
import hmac
from django.db import models
from merchants.models import Merchant


class WebhookEndpoint(models.Model):
    """Merchant-registered webhook URL."""

    EVENT_CHOICES = [
        ('payment.authorized',   'Payment Authorized'),
        ('payment.captured',     'Payment Captured'),
        ('payment.failed',       'Payment Failed'),
        ('refund.processed',     'Refund Processed'),
        ('refund.failed',        'Refund Failed'),
        ('settlement.processed', 'Settlement Processed'),
        ('order.paid',           'Order Paid'),
    ]

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant   = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='webhooks')
    url        = models.URLField(max_length=500)
    event_types = models.JSONField(default=list)   # e.g. ["payment.captured", "refund.processed"]
    secret     = models.CharField(max_length=255, default='')  # plain secret merchants use to verify
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'webhook_endpoints'
        indexes  = [models.Index(fields=['merchant', 'is_active'])]

    def __str__(self):
        return f"{self.merchant} → {self.url}"

    def sign_payload(self, payload: str) -> str:
        """Return HMAC-SHA256 hex digest of payload using this endpoint's secret."""
        return hmac.new(
            self.secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()


class WebhookEvent(models.Model):
    """One delivery attempt log per webhook endpoint per event."""

    STATUS_CHOICES = [
        ('pending',     'Pending'),
        ('delivered',   'Delivered'),
        ('failed',      'Failed'),
        ('dead_letter', 'Dead Letter'),
    ]

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint     = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name='events')
    event_type   = models.CharField(max_length=50)
    payload      = models.JSONField()
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempts     = models.PositiveIntegerField(default=0)
    last_attempt_at  = models.DateTimeField(null=True, blank=True)
    next_retry_at    = models.DateTimeField(null=True, blank=True)
    response_status  = models.IntegerField(null=True, blank=True)   # HTTP status from merchant
    response_body    = models.TextField(blank=True)
    failure_reason   = models.CharField(max_length=500, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'webhook_events'
        indexes  = [
            models.Index(fields=['status', 'next_retry_at']),
            models.Index(fields=['endpoint', 'event_type']),
        ]

    def __str__(self):
        return f"{self.event_type} → {self.endpoint.url} ({self.status})"