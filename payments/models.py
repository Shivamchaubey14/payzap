import uuid
from django.db import models
from merchants.models import Merchant


class Bank(models.Model):
    name         = models.CharField(max_length=100)
    code         = models.CharField(max_length=20, unique=True)   # our internal code
    gateway_code = models.CharField(max_length=20)                # code sent to gateway
    is_active    = models.BooleanField(default=True)

    class Meta:
        db_table = 'banks'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


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
    # Card-specific fields
    card_network = models.CharField(max_length=20, blank=True)   # visa/mastercard/rupay
    card_last4 = models.CharField(max_length=4, blank=True)
    card_token = models.CharField(max_length=255, blank=True)    # Vault token — never raw PAN
    bank = models.CharField(max_length=100, blank=True)
    is_3ds = models.BooleanField(default=False)
    three_ds_url = models.URLField(blank=True)                   # ACS redirect URL
    # UPI-specific fields
    upi_vpa        = models.CharField(max_length=100, blank=True)
    upi_intent_url = models.CharField(max_length=500, blank=True)
    upi_qr_code    = models.TextField(blank=True)
    
    # Net banking fields
    bank_code        = models.CharField(max_length=20, blank=True)
    bank_name        = models.CharField(max_length=100, blank=True)
    netbanking_url   = models.TextField(blank=True)   # redirect URL to bank login

    # Wallet fields
    wallet_provider  = models.CharField(max_length=30, blank=True)  # paytm/phonepe/amazonpay
    wallet_txn_id    = models.CharField(max_length=100, blank=True)
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
    
    
class Refund(models.Model):
    STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='refunds')
    amount = models.PositiveIntegerField()           # In paise
    currency = models.CharField(max_length=3, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initiated')
    reason = models.CharField(max_length=255, blank=True)
    notes = models.JSONField(default=dict, blank=True)
    initiated_by = models.CharField(max_length=100, blank=True)  # merchant or system
    gateway_refund_id = models.CharField(max_length=255, blank=True)
    failure_reason = models.CharField(max_length=500, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'refunds'
        indexes = [
            models.Index(fields=['payment', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Refund {self.id} — ₹{self.amount/100:.2f} ({self.status})"

    @property
    def amount_in_rupees(self):
        return self.amount / 100