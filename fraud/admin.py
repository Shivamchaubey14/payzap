from django.contrib import admin
from django.utils import timezone

from fraud.models import FraudRule, FraudSignal


@admin.register(FraudRule)
class FraudRuleAdmin(admin.ModelAdmin):
    list_display = ['rule_name', 'action', 'risk_score', 'threshold', 'is_active']
    list_filter = ['action', 'is_active']
    search_fields = ['rule_name', 'description']
    list_editable = ['is_active']


@admin.register(FraudSignal)
class FraudSignalAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'rule_triggered', 'risk_score', 'action_taken',
        'status', 'created_at'
    ]
    list_filter = ['action_taken', 'status', 'created_at']
    search_fields = ['rule_triggered', 'payment__id']
    readonly_fields = ['payment', 'rule', 'rule_triggered', 'risk_score',
                       'action_taken', 'details', 'created_at']
    actions = ['approve_signals', 'reject_signals']

    @admin.action(description='Approve selected signals (allow payment)')
    def approve_signals(self, request, queryset):
        queryset.update(
            status='approved',
            reviewed_by=str(request.user),
            reviewed_at=timezone.now(),
        )

    @admin.action(description='Reject selected signals (block payment)')
    def reject_signals(self, request, queryset):
        queryset.update(
            status='rejected',
            reviewed_by=str(request.user),
            reviewed_at=timezone.now(),
        )
