import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from merchants.authentication import APIKeyAuthentication
from webhooks.models import WebhookEndpoint, WebhookEvent
from webhooks.webhook_service import WebhookService


class WebhookEndpointCreateView(APIView):
    """POST /v1/webhooks/ — register a webhook URL"""
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        url = request.data.get('url')
        event_types = request.data.get('event_types', [])

        if not url:
            return Response({'error': 'url is required.'}, status=400)
        if not isinstance(event_types, list) or not event_types:
            return Response({'error': 'event_types must be a non-empty list.'}, status=400)

        secret = uuid.uuid4().hex  # auto-generate secret

        endpoint = WebhookEndpoint.objects.create(
            merchant=request.user,
            url=url,
            event_types=event_types,
            secret=secret,
            is_active=True,
        )

        return Response({
            'id':          str(endpoint.id),
            'url':         endpoint.url,
            'event_types': endpoint.event_types,
            'secret':      secret,  # shown once only
            'is_active':   endpoint.is_active,
            'created_at':  endpoint.created_at,
        }, status=status.HTTP_201_CREATED)


class WebhookEndpointListView(APIView):
    """GET /v1/webhooks/ — list merchant's webhooks"""
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        endpoints = WebhookEndpoint.objects.filter(
            merchant=request.user,
            is_active=True,
        ).values('id', 'url', 'event_types', 'is_active', 'created_at')

        return Response({'webhooks': list(endpoints)})


class WebhookTestView(APIView):
    """POST /v1/webhooks/{id}/test/ — send a test event"""
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, webhook_id):
        try:
            endpoint = WebhookEndpoint.objects.get(
                id=webhook_id,
                merchant=request.user,
                is_active=True,
            )
        except WebhookEndpoint.DoesNotExist:
            return Response({'error': 'Webhook not found.'}, status=404)

        test_payload = {
            'event': 'test',
            'data':  {'message': 'This is a test webhook from PayZap.'},
        }

        service = WebhookService()
        event = WebhookEvent.objects.create(
            endpoint=endpoint,
            event_type='test',
            payload=test_payload,
            status='pending',
            next_retry_at=timezone.now(),
        )
        service._attempt_delivery(event)
        event.refresh_from_db()

        return Response({
            'status':          event.status,
            'response_status': event.response_status,
            'attempts':        event.attempts,
        })
