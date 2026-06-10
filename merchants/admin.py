from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from merchants.models import Merchant, APIKey, KYCDocument
from merchants.kyc_service import KYCService


class KYCDocumentInline(admin.TabularInline):
    model = KYCDocument
    extra = 0
    readonly_fields = ['document_type', 'file_name', 'status', 'uploaded_at', 'view_link']
    fields = ['document_type', 'file_name', 'status', 'uploaded_at', 'view_link']

    def view_link(self, obj):
        return format_html(
            '<a href="/admin/kyc/view/{}/" target="_blank">View</a>',
            obj.id
        )
    view_link.short_description = 'Document'


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = [
        'business_name', 'email', 'kyc_status',
        'is_live', 'is_active', 'created_at'
    ]
    list_filter = ['kyc_status', 'is_live', 'is_active']
    search_fields = ['business_name', 'email', 'pan']
    readonly_fields = ['id', 'created_at', 'updated_at']
    inlines = [KYCDocumentInline]
    actions = ['approve_kyc', 'reject_kyc', 'suspend_merchant', 'unsuspend_merchant']

    @admin.action(description='Approve KYC for selected merchants')
    def approve_kyc(self, request, queryset):
        service = KYCService()
        approved = 0
        for merchant in queryset.filter(kyc_status__in=('submitted', 'under_review')):
            try:
                service.approve_kyc(merchant, reviewed_by=str(request.user))
                approved += 1
            except ValueError:
                pass
        self.message_user(request, f'{approved} merchant(s) KYC approved.')

    @admin.action(description='Reject KYC (reason: incomplete documents)')
    def reject_kyc(self, request, queryset):
        service = KYCService()
        rejected = 0
        for merchant in queryset.filter(kyc_status__in=('submitted', 'under_review')):
            try:
                service.reject_kyc(
                    merchant,
                    reason='Documents are incomplete or unclear. Please re-upload.',
                    reviewed_by=str(request.user)
                )
                rejected += 1
            except ValueError:
                pass
        self.message_user(request, f'{rejected} merchant(s) KYC rejected.')

    @admin.action(description='Suspend merchant accounts')
    def suspend_merchant(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f'{queryset.count()} merchant(s) suspended.')

    @admin.action(description='Unsuspend merchant accounts')
    def unsuspend_merchant(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f'{queryset.count()} merchant(s) unsuspended.')


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ['merchant', 'document_type', 'status', 'file_name', 'uploaded_at']
    list_filter = ['document_type', 'status']
    search_fields = ['merchant__business_name', 'merchant__email']
    readonly_fields = ['id', 'merchant', 'file_key', 'uploaded_at']


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ['key_prefix', 'merchant', 'is_live', 'is_active', 'last_used_at']
    list_filter = ['is_live', 'is_active']
    search_fields = ['key_prefix', 'merchant__email']
    readonly_fields = ['id', 'key_hash', 'created_at']