from django.utils import timezone
from datetime import timedelta
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from monitoring.metrics import payment_created_total
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from payments.models import Order, Payment, Refund
from payments.refund_service import RefundService
from payments.serializers import OrderCreateSerializer, OrderResponseSerializer, RefundSerializer
from merchants.authentication import APIKeyAuthentication
from payments.services import PaymentService
from payments.serializers import PaymentResponseSerializer
from payments.models import PaymentLink, VirtualAccount
from payments.payment_link_service import PaymentLinkService
from payments.virtual_account_service import VirtualAccountService
from payments.serializers import PaymentLinkSerializer, VirtualAccountSerializer
from django.shortcuts import get_object_or_404
from django.utils import timezone


class OrderCreateView(APIView):
    """
    POST /v1/orders
    Creates a payment order. Requires API key auth.
    Idempotency handled by IdempotencyMiddleware.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
    summary="Create a payment order",
    description="Creates a new order. Use the returned order_id to initiate payment via Checkout.js or API.",
    responses={201: None},
    examples=[
        OpenApiExample(
            'Example Request',
            value={
                "amount": 50000,
                "currency": "INR",
                "receipt": "order_rcpt_001",
                "notes": {"customer_name": "Rahul Sharma"}
            },
            request_only=True,
        )
            ]
                )

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

            elif method == 'upi':
                from payments.upi_service import UPIService
                service = UPIService()
                upi_vpa = request.data.get('upi_vpa', '')
                if upi_vpa:
                    # UPI Collect flow
                    payment = service.process_upi_collect(order, {'upi_vpa': upi_vpa})
                else:
                    # UPI Intent flow — generate QR
                    merchant_name = request.user.business_name
                    payment = service.process_upi_intent(order, merchant_name)
            elif method == 'netbanking':
                from payments.netbanking_service import NetBankingService
                bank_code = request.data.get('bank_code', '')
                if not bank_code:
                    return Response({'error': 'bank_code is required for netbanking.'}, status=400)
                service = NetBankingService()
                payment = service.process_netbanking(order, bank_code)

            elif method == 'wallet':
                from payments.wallet_service import WalletService
                wallet_provider = request.data.get('wallet_provider', '')
                if not wallet_provider:
                    return Response({'error': 'wallet_provider is required for wallet payments.'}, status=400)
                service = WalletService()
                payment = service.process_wallet_payment(order, wallet_provider)
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
    
class BankListView(APIView):
    """
    GET /v1/banks/
    Returns list of supported net banking banks.
    No auth required — public endpoint.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        from payments.models import Bank
        banks = Bank.objects.filter(is_active=True).values('name', 'code')
        return Response({'banks': list(banks)})
    
    
class RefundCreateView(APIView):
    """
    POST /v1/refunds/
    Initiates a full or partial refund on a captured payment.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payment_id = request.data.get('payment_id')
        amount = request.data.get('amount')

        if not payment_id:
            return Response({'error': 'payment_id is required.'}, status=400)
        if not amount:
            return Response({'error': 'amount is required.'}, status=400)

        try:
            payment = Payment.objects.select_related('order__merchant').get(
                id=payment_id,
                order__merchant=request.user,
            )
        except Payment.DoesNotExist:
            return Response({'error': 'Payment not found.'}, status=404)

        service = RefundService()
        try:
            refund = service.initiate_refund(
                payment=payment,
                amount=int(amount),
                reason=request.data.get('reason', ''),
                notes=request.data.get('notes', {}),
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

        return Response(
            RefundSerializer(refund).data,
            status=status.HTTP_201_CREATED,
        )


class RefundDetailView(APIView):
    """
    GET /v1/refunds/{id}/
    Fetch refund status and details.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, refund_id):
        service = RefundService()
        try:
            refund = service.get_refund(str(refund_id), request.user)
        except ValueError:
            return Response({'error': 'Refund not found.'}, status=404)

        return Response(RefundSerializer(refund).data)



class PaymentLinkCreateView(APIView):
    """POST /v1/payment_links/ — create a shareable payment link"""
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        service = PaymentLinkService()
        try:
            link = service.create_link(request.user, request.data)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        return Response(
            PaymentLinkSerializer(link, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class PaymentLinkListView(APIView):
    """GET /v1/payment_links/ — list merchant's payment links"""
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        links = PaymentLink.objects.filter(
            merchant=request.user
        ).order_by('-created_at')
        return Response({
            'count': links.count(),
            'items': PaymentLinkSerializer(
                links, many=True, context={'request': request}
            ).data,
        })


class PaymentLinkDetailView(APIView):
    """GET /v1/payment_links/{id}/ — fetch a specific link"""
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, link_id):
        try:
            link = PaymentLink.objects.get(id=link_id, merchant=request.user)
        except PaymentLink.DoesNotExist:
            return Response({'error': 'Payment link not found.'}, status=404)
        return Response(PaymentLinkSerializer(link, context={'request': request}).data)

    def delete(self, request, link_id):
        try:
            link = PaymentLink.objects.get(id=link_id, merchant=request.user)
        except PaymentLink.DoesNotExist:
            return Response({'error': 'Payment link not found.'}, status=404)
        service = PaymentLinkService()
        service.disable_link(link, request.user)
        return Response({'status': 'disabled'})


class PaymentLinkCheckoutView(APIView):
    """
    GET /pay/{slug}/ — public hosted checkout page for a payment link.
    No auth required — this is what customers open.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request, slug):
        service = PaymentLinkService()
        try:
            link = service.get_link(slug)
        except ValueError:
            return Response({'error': 'Payment link not found or expired.'}, status=404)

        if not link.is_usable:
            return Response({'error': 'This payment link is no longer active.'}, status=410)

        return Response({
            'slug':        link.slug,
            'amount':      link.amount,
            'currency':    link.currency,
            'description': link.description,
            'merchant':    link.merchant.business_name,
            'expires_at':  link.expires_at,
        })


class VirtualAccountCreateView(APIView):
    """POST /v1/virtual_accounts/ — create a virtual UPI/NEFT collector"""
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        service = VirtualAccountService()
        try:
            va = service.create_virtual_account(request.user, request.data)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        return Response(
            VirtualAccountSerializer(va).data,
            status=status.HTTP_201_CREATED,
        )


class VirtualAccountDetailView(APIView):
    """GET /v1/virtual_accounts/{id}/ — fetch VA details"""
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, va_id):
        try:
            va = VirtualAccount.objects.get(id=va_id, merchant=request.user)
        except VirtualAccount.DoesNotExist:
            return Response({'error': 'Virtual account not found.'}, status=404)
        return Response(VirtualAccountSerializer(va).data)

    def delete(self, request, va_id):
        try:
            va = VirtualAccount.objects.get(id=va_id, merchant=request.user)
        except VirtualAccount.DoesNotExist:
            return Response({'error': 'Virtual account not found.'}, status=404)
        service = VirtualAccountService()
        try:
            va = service.close_account(va, request.user)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        return Response(VirtualAccountSerializer(va).data)


class VirtualAccountCreditView(APIView):
    """
    POST /v1/virtual_accounts/{id}/credit/ — simulate incoming bank credit.
    In production this is called by bank callback, not directly.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, va_id):
        try:
            va = VirtualAccount.objects.get(id=va_id, merchant=request.user)
        except VirtualAccount.DoesNotExist:
            return Response({'error': 'Virtual account not found.'}, status=404)

        amount = request.data.get('amount')
        if not amount:
            return Response({'error': 'amount is required.'}, status=400)

        service = VirtualAccountService()
        try:
            payment = service.record_credit(
                va=va,
                amount=int(amount),
                payment_method=request.data.get('method', 'upi'),
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

        return Response(
            PaymentResponseSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )