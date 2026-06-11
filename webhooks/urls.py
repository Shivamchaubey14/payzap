from django.urls import path

from webhooks.views import (
    WebhookEndpointCreateView,
    WebhookEndpointListView,
    WebhookTestView,
)

urlpatterns = [
    path('webhooks/', WebhookEndpointListView.as_view(), name='webhook-list'),
    path('webhooks/create/', WebhookEndpointCreateView.as_view(), name='webhook-create'),
    path('webhooks/<uuid:webhook_id>/test/', WebhookTestView.as_view(), name='webhook-test'),
]
