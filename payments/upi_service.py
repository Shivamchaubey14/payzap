import base64
import logging
from io import BytesIO

from django.db import transaction
from django.utils import timezone

from payments.models import Order, Payment
from payments.processors.mock_gateway import MockBankGateway
from payments.upi_validator import generate_upi_intent_url, normalize_vpa, validate_vpa

logger = logging.getLogger(__name__)


class UPIService:
    """
    Handles both UPI flows:
    - Collect: merchant sends debit request to customer VPA
    - Intent:  deep link / QR code for customer to pay from their UPI app
    """

    def process_upi_collect(self, order: Order, upi_data: dict) -> Payment:
        """Customer enters VPA — we send a debit request."""
        vpa = upi_data.get('upi_vpa', '').strip()

        # Validate VPA format
        if not validate_vpa(vpa):
            payment = Payment.objects.create(
                order=order,
                method='upi',
                amount=order.amount,
                currency=order.currency,
                status='failed',
                error_code='INVALID_VPA',
                failure_reason=f'Invalid UPI VPA format: {vpa}',
            )
            return payment

        vpa = normalize_vpa(vpa)

        # Create payment record
        payment = Payment.objects.create(
            order=order,
            method='upi',
            amount=order.amount,
            currency=order.currency,
            upi_vpa=vpa,
            status='processing',
        )

        # Mark order as attempted
        Order.objects.filter(id=order.id).update(status='attempted')

        # Call gateway (mock simulates NPCI collect request)
        gateway = MockBankGateway()
        result = gateway.authorize(payment, {**upi_data, 'method': 'upi'})

        # Update payment state
        with transaction.atomic():
            update_data = {
                'gateway_txn_id': result.gateway_txn_id or '',
                'gateway_response': result.raw_response or {},
            }
            if result.success:
                update_data['status'] = result.status   # 'authorized'
            else:
                update_data['status'] = 'failed'
                update_data['error_code'] = result.error_code or ''
                update_data['failure_reason'] = result.error_message or ''
                update_data['failed_at'] = timezone.now()

            Payment.objects.filter(id=payment.id).update(**update_data)
            payment.status = update_data['status']

        return payment

    def process_upi_intent(self, order: Order, merchant_name: str) -> Payment:
        """Generate UPI Intent deep link and QR code — no VPA needed."""
        import uuid
        transaction_ref = f"payzap_{uuid.uuid4().hex[:12]}"

        # Use a generic PayZap collect VPA for intent payments
        collect_vpa = 'payzap@upi'

        intent_url = generate_upi_intent_url(
            vpa=collect_vpa,
            amount=order.amount,
            merchant_name=merchant_name,
            transaction_ref=transaction_ref,
            currency=order.currency,
        )

        qr_b64 = self._generate_qr_code(intent_url)

        payment = Payment.objects.create(
            order=order,
            method='upi',
            amount=order.amount,
            currency=order.currency,
            upi_vpa=collect_vpa,
            upi_intent_url=intent_url,
            upi_qr_code=qr_b64,
            status='processing',
        )

        Order.objects.filter(id=order.id).update(status='attempted')

        logger.info(f"UPI Intent created for order {order.id}, ref={transaction_ref}")
        return payment

    def _generate_qr_code(self, data: str) -> str:
        """Generate QR code as base64 PNG string."""
        try:
            import qrcode
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
        except ImportError:
            logger.warning("qrcode library not installed — QR skipped")
            return ''
