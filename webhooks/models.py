import uuid
from django.db import models
from merchants.models import Merchant


class WebhookEndpoint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='webhooks')
    url = models.URLField(max_length=500)
    event_types = models.JSONField(default=list)         # ["payment.captured", "refund.processed"]
    secret_hash = models.CharField(max_length=128)       # Hashed signing secret
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'webhooks'
        indexes = [
            models.Index(fields=['merchant', 'is_active']),
        ]

    def __str__(self):
        return f"Webhook {self.url} ({self.merchant.business_name})"


class WebhookEvent(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('dead_letter', 'Dead Letter'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    webhook = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=100)        # e.g. "payment.captured"
    payload = models.JSONField()                         # Full event payload
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    response_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'webhook_events'
        indexes = [
            models.Index(fields=['webhook', 'status']),
            models.Index(fields=['status', 'next_retry_at']),
            models.Index(fields=['event_type']),
        ]

    def __str__(self):
        return f"{self.event_type} — {self.status} (attempt {self.attempts})"