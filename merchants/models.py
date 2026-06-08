import uuid
import secrets
import hashlib
from django.db import models


class Merchant(models.Model):
    KYC_STATUS = [
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15)
    pan = models.CharField(max_length=10, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    bank_account_number = models.CharField(max_length=20, blank=True)
    bank_ifsc = models.CharField(max_length=11, blank=True)
    kyc_status = models.CharField(max_length=20, choices=KYC_STATUS, default='pending')
    fee_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0.0200)  # 2% default
    is_live = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_authenticated(self):
        return True

    class Meta:
        db_table = 'merchants'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['kyc_status']),
        ]

    def __str__(self):
        return f"{self.business_name} ({self.email})"


class APIKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='api_keys')
    key_prefix = models.CharField(max_length=20)        # e.g. rzp_live_ABC123
    key_hash = models.CharField(max_length=128)         # PBKDF2-SHA256 hash — never raw
    is_live = models.BooleanField(default=False)
    permissions = models.JSONField(default=dict)        # e.g. {"payments": true, "refunds": true}
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'api_keys'
        indexes = [
            models.Index(fields=['key_prefix']),
            models.Index(fields=['merchant', 'is_active']),
        ]

    def __str__(self):
        return f"{self.key_prefix} ({'live' if self.is_live else 'test'})"

    @staticmethod
    def generate_key(is_live=False):
        """Generate a new API key. Returns (full_key, prefix, hash)."""
        raw = secrets.token_urlsafe(32)
        prefix = f"{'rzp_live' if is_live else 'rzp_test'}_{raw[:8]}"
        full_key = f"{prefix}_{raw[8:]}"
        key_hash = hashlib.pbkdf2_hmac('sha256', full_key.encode(), b'payzap_salt', 100000).hex()
        return full_key, prefix, key_hash