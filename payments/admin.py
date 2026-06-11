from django.contrib import admin

from payments.models import Order, Payment, Refund


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'merchant', 'amount_display', 'currency', 'status', 'created_at']
    list_filter = ['status', 'currency', 'created_at']
    search_fields = ['id', 'merchant__email', 'merchant__business_name', 'receipt']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def amount_display(self, obj):
        return f'₹{obj.amount / 100:.2f}'
    amount_display.short_description = 'Amount'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'merchant_email', 'amount_display',
        'method', 'status', 'gateway_txn_id', 'created_at'
    ]
    list_filter = ['status', 'method', 'created_at']
    search_fields = ['id', 'order__merchant__email', 'gateway_txn_id']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']
    actions = ['mark_as_failed', 'retry_capture']

    def merchant_email(self, obj):
        return obj.order.merchant.email
    merchant_email.short_description = 'Merchant'

    def amount_display(self, obj):
        return f'₹{obj.amount / 100:.2f}'
    amount_display.short_description = 'Amount'

    @admin.action(description='Mark selected payments as failed')
    def mark_as_failed(self, request, queryset):
        updated = queryset.filter(
            status__in=('created', 'processing')
        ).update(status='failed')
        self.message_user(request, f'{updated} payment(s) marked as failed.')

    @admin.action(description='Retry capture for authorized payments')
    def retry_capture(self, request, queryset):
        from payments.services import PaymentService
        service = PaymentService()
        retried = 0
        for payment in queryset.filter(status='authorized'):
            try:
                service.capture_payment(str(payment.id), payment.order.merchant)
                retried += 1
            except Exception:
                pass
        self.message_user(request, f'{retried} payment(s) capture retried.')


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'payment', 'amount_display',
        'status', 'reason', 'created_at'
    ]
    list_filter = ['status', 'reason', 'created_at']
    search_fields = ['id', 'payment__id', 'payment__order__merchant__email']
    readonly_fields = ['id', 'payment', 'gateway_refund_id', 'created_at']
    ordering = ['-created_at']

    def amount_display(self, obj):
        return f'₹{obj.amount / 100:.2f}'
    amount_display.short_description = 'Amount'
