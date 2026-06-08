from django.utils import timezone
from datetime import timedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from payments.models import Order, Payment
from payments.serializers import OrderCreateSerializer, OrderResponseSerializer
from merchants.authentication import APIKeyAuthentication


class OrderCreateView(APIView):
    """
    POST /v1/orders
    Creates a payment order. Requires API key auth.
    Idempotency handled by IdempotencyMiddleware.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = OrderCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        merchant = request.user

        # Check for duplicate idempotency key for this merchant
        existing = Order.objects.filter(
            merchant=merchant,
            idempotency_key=data['idempotency_key']
        ).first()

        if existing:
            return Response(
                OrderResponseSerializer(existing).data,
                status=status.HTTP_200_OK  # Return existing, not 201
            )

        # Create order with 30-minute expiry
        order = Order.objects.create(
            merchant=merchant,
            amount=data['amount'],
            currency=data.get('currency', 'INR'),
            receipt=data.get('receipt', ''),
            notes=data.get('notes', {}),
            idempotency_key=data['idempotency_key'],
            expires_at=timezone.now() + timedelta(minutes=30),
        )

        return Response(
            OrderResponseSerializer(order).data,
            status=status.HTTP_201_CREATED
        )


class OrderDetailView(APIView):
    """
    GET /v1/orders/{id}
    Fetch order details. Enforces merchant ownership — 403 if wrong merchant.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Ownership check — merchant can only see their own orders
        if order.merchant != request.user:
            return Response(
                {'error': 'You do not have permission to view this order.'},
                status=status.HTTP_403_FORBIDDEN
            )

        return Response(OrderResponseSerializer(order).data)


class OrderListView(APIView):
    """
    GET /v1/orders
    List all orders for the authenticated merchant with filters.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        merchant = request.user
        queryset = Order.objects.filter(merchant=merchant).order_by('-created_at')

        # Optional filters
        order_status = request.query_params.get('status')
        currency = request.query_params.get('currency')
        from_date = request.query_params.get('from')
        to_date = request.query_params.get('to')

        if order_status:
            queryset = queryset.filter(status=order_status)
        if currency:
            queryset = queryset.filter(currency=currency)
        if from_date:
            queryset = queryset.filter(created_at__date__gte=from_date)
        if to_date:
            queryset = queryset.filter(created_at__date__lte=to_date)

        # Manual pagination
        page = int(request.query_params.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        total = queryset.count()

        return Response({
            'count': total,
            'page': page,
            'total_pages': (total + page_size - 1) // page_size,
            'items': OrderResponseSerializer(queryset[start:end], many=True).data,
        })