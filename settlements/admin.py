from django.contrib import admin
from settlements.models import Settlement


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'merchant', 'amount_display', 'fees_display',
        'status', 'utr_number', 'settled_at', 'created_at'
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['merchant__email', 'merchant__business_name', 'utr_number']
    readonly_fields = [
        'id', 'merchant', 'amount', 'fees', 'tax',
        'bank_account_number', 'bank_ifsc',
        'settlement_from', 'settlement_to', 'created_at'
    ]
    ordering = ['-created_at']
    actions = ['retry_failed_settlement', 'mark_on_hold']

    def amount_display(self, obj):
        return f'₹{obj.amount / 100:.2f}'
    amount_display.short_description = 'Payout Amount'

    def fees_display(self, obj):
        return f'₹{obj.fees / 100:.2f}'
    fees_display.short_description = 'Fees'

    @admin.action(description='Retry failed settlements')
    def retry_failed_settlement(self, request, queryset):
        from settlements.tasks import _initiate_bank_payout
        retried = 0
        for settlement in queryset.filter(status='failed'):
            try:
                _initiate_bank_payout(settlement)
                retried += 1
            except Exception:
                pass
        self.message_user(request, f'{retried} settlement(s) retried.')

    @admin.action(description='Put settlements on hold')
    def mark_on_hold(self, request, queryset):
        updated = queryset.filter(
            status__in=('pending', 'processing')
        ).update(status='on_hold')
        self.message_user(request, f'{updated} settlement(s) put on hold.')