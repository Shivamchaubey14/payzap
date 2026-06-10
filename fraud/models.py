import uuid
from django.db import models
from payments.models import Payment


class FraudRule(models.Model):
    ACTION_CHOICES = [
        ('block', 'Block'),
        ('flag', 'Flag for Review'),
        ('step_up', 'Step-up Auth'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule_name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    risk_score = models.PositiveIntegerField(default=0)  # Added to total risk score
    threshold = models.IntegerField(default=0)           # Rule-specific threshold
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fraud_rules'

    def __str__(self):
        return f"{self.rule_name} ({self.action})"


class FraudSignal(models.Model):
    STATUS_CHOICES = [
        ('pending_review', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name='fraud_signals'
    )
    rule = models.ForeignKey(
        FraudRule, on_delete=models.SET_NULL, null=True, related_name='signals'
    )
    rule_triggered = models.CharField(max_length=100)
    risk_score = models.PositiveIntegerField(default=0)
    action_taken = models.CharField(max_length=20)
    details = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending_review'
    )
    reviewed_by = models.CharField(max_length=100, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fraud_signals'
        indexes = [
            models.Index(fields=['payment', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"FraudSignal {self.id} — {self.rule_triggered} ({self.action_taken})"