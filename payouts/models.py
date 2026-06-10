import uuid
from django.db import models
from merchants.models import Merchant


class Payout(models.Model):
    MODE_CHOICES = [
        ('NEFT', 'NEFT'),
        ('IMPS', 'IMPS'),
        ('UPI', 'UPI'),
    ]

    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed'),
    ]

    PURPOSE_CHOICES = [
        ('payout', 'Payout'),
        ('refund', 'Refund'),
        ('cashback', 'Cashback'),
        ('salary', 'Salary'),
        ('vendor', 'Vendor Payment'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name='payouts')
    amount = models.PositiveIntegerField()              # In paise
    currency = models.CharField(max_length=3, default='INR')
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='IMPS')
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default='payout')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')

    # Beneficiary details
    beneficiary_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=20, blank=True)
    ifsc = models.CharField(max_length=11, blank=True)
    upi_id = models.CharField(max_length=100, blank=True)

    # Result fields
    utr_number = models.CharField(max_length=100, blank=True)
    failure_reason = models.CharField(max_length=500, blank=True)
    reference_id = models.CharField(max_length=255, blank=True)  # merchant's own ref

    # Bulk batch reference
    batch_id = models.CharField(max_length=100, blank=True)

    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payouts'
        indexes = [
            models.Index(fields=['merchant', 'status']),
            models.Index(fields=['batch_id']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Payout {self.id} — ₹{self.amount/100:.2f} to {self.beneficiary_name} ({self.status})"