from django.contrib import admin
from webhooks.models import WebhookEndpoint, WebhookEvent


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ['id', 'merchant', 'url', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['merchant__email', 'url']
    readonly_fields = ['id', 'created_at', 'updated_at']
    actions = ['deactivate_endpoints']

    @admin.action(description='Deactivate selected webhook endpoints')
    def deactivate_endpoints(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f'{queryset.count()} endpoint(s) deactivated.')


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'endpoint_url', 'event_type',
        'status', 'attempts', 'last_attempt_at'
    ]
    list_filter = ['status', 'event_type', 'created_at']
    search_fields = ['endpoint__merchant__email', 'event_type']
    readonly_fields = [
        'id', 'endpoint', 'event_type', 'payload',
        'attempts', 'last_attempt_at', 'response_status',
        'response_body', 'failure_reason', 'created_at'
    ]
    ordering = ['-created_at']
    actions = ['retry_delivery', 'move_to_dead_letter']

    def endpoint_url(self, obj):
        return obj.endpoint.url
    endpoint_url.short_description = 'Endpoint'

    @admin.action(description='Force retry delivery for selected events')
    def retry_delivery(self, request, queryset):
        from webhooks.webhook_service import WebhookService
        service = WebhookService()
        retried = 0
        for event in queryset.filter(status__in=('failed', 'dead_letter')):
            try:
                event.status = 'failed'
                event.next_retry_at = None
                event.save()
                service._attempt_delivery(event)
                retried += 1
            except Exception:
                pass
        self.message_user(request, f'{retried} webhook(s) retried.')

    @admin.action(description='Move selected events to dead letter queue')
    def move_to_dead_letter(self, request, queryset):
        updated = queryset.exclude(status='dead_letter').update(status='dead_letter')
        self.message_user(request, f'{updated} event(s) moved to dead letter.')