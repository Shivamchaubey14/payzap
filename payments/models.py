import uuid
from django.db import models
from merchants.models import Merchant


class Order(models.Model):
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('attempted', 'Attempted'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('expired', 'Expired'),
    ]

    CURRENCY_CHOICES = [
        ('INR', 'Indian Rupee'),
        ('USD', 'US Dollar'),
        ('EUR', 'Euro'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name='orders')
    amount = models.PositiveIntegerField()               # Amount in paise (100 = ₹1)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='created')
    receipt = models.CharField(max_length=100, blank=True)
    notes = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'orders'
        indexes = [
            models.Index(fields=['merchant', 'status']),
            models.Index(fields=['idempotency_key']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Order {self.id} — ₹{self.amount/100:.2f} ({self.status})"

    @property
    def amount_in_rupees(self):
        return self.amount / 100


class Payment(models.Model):
    METHOD_CHOICES = [
        ('card', 'Card'),
        ('upi', 'UPI'),
        ('netbanking', 'Net Banking'),
        ('wallet', 'Wallet'),
        ('emi', 'EMI'),
        ('paylater', 'Pay Later'),
    ]

    STATUS_CHOICES = [
        ('created', 'Created'),
        ('processing', 'Processing'),
        ('authorized', 'Authorized'),
        ('captured', 'Captured'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
        ('partially_refunded', 'Partially Refunded'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='payments')
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='created')
    amount = models.PositiveIntegerField()               # In paise
    currency = models.CharField(max_length=3, default='INR')
    gateway_txn_id = models.CharField(max_length=255, blank=True)   # Bank's transaction ID
    gateway_response = models.JSONField(default=dict, blank=True)   # Raw bank response
    amount_refunded = models.PositiveIntegerField(default=0)
    captured_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=500, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments'
        indexes = [
            models.Index(fields=['order', 'status']),
            models.Index(fields=['gateway_txn_id']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['method', 'status']),
        ]

    def __str__(self):
        return f"Payment {self.id} — {self.method} — ₹{self.amount/100:.2f} ({self.status})"

    @property
    def refundable_amount(self):
        return self.amount - self.amount_refunded