import uuid
from django.db import models
from merchants.models import Merchant


class Settlement(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
        ('on_hold', 'On Hold'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name='settlements')
    amount = models.PositiveIntegerField()               # Net payout in paise
    fees = models.PositiveIntegerField(default=0)        # Platform fees deducted
    tax = models.PositiveIntegerField(default=0)         # GST on fees
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    utr_number = models.CharField(max_length=100, blank=True)   # Bank UTR after payout
    bank_account_number = models.CharField(max_length=20, blank=True)
    bank_ifsc = models.CharField(max_length=11, blank=True)
    settlement_from = models.DateTimeField()
    settlement_to = models.DateTimeField()
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'settlements'
        indexes = [
            models.Index(fields=['merchant', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"Settlement {self.id} — ₹{self.amount/100:.2f} ({self.status})"