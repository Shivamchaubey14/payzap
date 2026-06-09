from django.utils import timezone
from datetime import timedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from payments.models import Order, Payment
from payments.serializers import OrderCreateSerializer, OrderResponseSerializer
from merchants.authentication import APIKeyAuthentication
from payments.services import PaymentService
from payments.serializers import PaymentResponseSerializer


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
        


class PaymentCreateView(APIView):
    """
    POST /v1/payments/
    Processes a payment for an existing order.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        order_id = request.data.get('order_id')
        if not order_id:
            return Response({'error': 'order_id is required.'}, status=400)

        try:
            order = Order.objects.get(id=order_id, merchant=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=404)

        if order.status in ('paid', 'failed', 'expired'):
            return Response(
                {'error': f'Order is already {order.status}.'},
                status=400
            )

        method = request.data.get('method', 'card')
        payment_data = {
            'method': method,
            'card_number': request.data.get('card_number', ''),
            'ip_address': request.META.get('REMOTE_ADDR'),
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
        }

        try:
            if method == 'card' and payment_data.get('card_number'):
                from payments.card_service import CardPaymentService
                service = CardPaymentService()
                payment = service.process_card_payment(order, payment_data)
            else:
                from payments.services import PaymentService
                service = PaymentService()
                payment = service.process_payment(order, payment_data)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

        return Response(
            PaymentResponseSerializer(payment).data,
            status=status.HTTP_201_CREATED
        )


class PaymentDetailView(APIView):
    """
    GET /v1/payments/{id}
    Fetch payment status and details.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, payment_id):
        try:
            payment = Payment.objects.select_related('order__merchant').get(id=payment_id)
        except Payment.DoesNotExist:
            return Response({'error': 'Payment not found.'}, status=404)

        if payment.order.merchant != request.user:
            return Response({'error': 'Permission denied.'}, status=403)

        return Response(PaymentResponseSerializer(payment).data)


class PaymentCaptureView(APIView):
    """
    POST /v1/payments/{id}/capture
    Capture an authorized payment.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, payment_id):
        try:
            payment = Payment.objects.select_related('order__merchant').get(id=payment_id)
        except Payment.DoesNotExist:
            return Response({'error': 'Payment not found.'}, status=404)

        if payment.order.merchant != request.user:
            return Response({'error': 'Permission denied.'}, status=403)

        amount = request.data.get('amount')
        service = PaymentService()
        try:
            payment = service.capture_payment(payment, amount)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

        return Response(PaymentResponseSerializer(payment).data)