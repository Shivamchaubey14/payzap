import logging
from django.db import transaction
from django.utils import timezone
from django.core.cache import cache
from payments.models import Order, Payment
from payments.processors.mock_gateway import MockBankGateway

logger = logging.getLogger(__name__)


class PaymentService:
    """
    Orchestrates the full payment processing flow.
    Handles distributed locking, state machines, and atomic DB updates.
    """
    LOCK_TTL = 30           # seconds — max time to hold a payment lock
    LOCK_PREFIX = 'payment_lock'

    def __init__(self):
        self.gateway = MockBankGateway()

    def process_payment(self, order: Order, payment_data: dict) -> Payment:
        """
        Main entry point. Creates a Payment and processes it end-to-end.
        Steps:
          1. Validate order is in correct state
          2. Create payment record
          3. Acquire Redis distributed lock
          4. Call gateway
          5. Atomically update payment state
          6. Return payment
        """
        # Step 1 — Validate order
        if order.status not in ('created', 'attempted'):
            raise ValueError(f'Order {order.id} is not payable (status: {order.status})')

        # Step 2 — Create payment record
        payment = Payment.objects.create(
            order=order,
            method=payment_data.get('method', 'card'),
            amount=order.amount,
            currency=order.currency,
            ip_address=payment_data.get('ip_address'),
            user_agent=payment_data.get('user_agent', ''),
        )

        # Mark order as attempted
        Order.objects.filter(id=order.id).update(status='attempted')

        # Step 3 — Acquire distributed lock
        lock_key = f"{self.LOCK_PREFIX}:{payment.id}"
        lock_acquired = cache.add(lock_key, '1', self.LOCK_TTL)

        if not lock_acquired:
            logger.warning(f"Could not acquire lock for payment {payment.id}")
            self._fail_payment(payment, 'LOCK_FAILED', 'Payment already being processed.')
            return payment

        try:
            # Step 4 — Call gateway
            logger.info(f"Processing payment {payment.id} via {self.gateway.__class__.__name__}")
            result = self.gateway.authorize(payment, payment_data)

            # Step 5 — Atomic state update
            self._update_payment_state(payment, result)

        except Exception as e:
            logger.error(f"Payment {payment.id} failed with exception: {e}")
            self._fail_payment(payment, 'INTERNAL_ERROR', str(e))

        finally:
            # Always release the lock
            cache.delete(lock_key)

        return payment

    def capture_payment(self, payment: Payment, amount: int = None) -> Payment:
        """
        Capture an authorized payment.
        If amount is None, captures the full authorized amount.
        """
        if payment.status != 'authorized':
            raise ValueError(f'Payment {payment.id} is not authorized (status: {payment.status})')

        capture_amount = amount or payment.amount
        lock_key = f"{self.LOCK_PREFIX}:{payment.id}"
        lock_acquired = cache.add(lock_key, '1', self.LOCK_TTL)

        if not lock_acquired:
            raise ValueError('Payment is already being processed.')

        try:
            result = self.gateway.capture(payment, capture_amount)
            with transaction.atomic():
                payment_obj = Payment.objects.select_for_update().get(id=payment.id)
                if result.success:
                    payment_obj.status = 'captured'
                    payment_obj.captured_at = timezone.now()
                    payment_obj.gateway_txn_id = result.gateway_txn_id
                    payment_obj.gateway_response = result.raw_response
                    Order.objects.filter(id=payment_obj.order_id).update(status='paid')
                else:
                    payment_obj.status = 'failed'
                    payment_obj.error_code = result.error_code
                    payment_obj.failure_reason = result.error_message
                payment_obj.save()
                return payment_obj
        finally:
            cache.delete(lock_key)

    @transaction.atomic
    def _update_payment_state(self, payment: Payment, result):
        """Atomically update payment using select_for_update to prevent race conditions."""
        payment_obj = Payment.objects.select_for_update().get(id=payment.id)

        if result.success:
            payment_obj.status = result.status
            payment_obj.gateway_txn_id = result.gateway_txn_id
            payment_obj.gateway_response = result.raw_response
            if result.status == 'captured':
                payment_obj.captured_at = timezone.now()
                Order.objects.filter(id=payment_obj.order_id).update(status='paid')
        else:
            payment_obj.status = 'failed'
            payment_obj.error_code = result.error_code
            payment_obj.failure_reason = result.error_message
            payment_obj.failed_at = timezone.now()
            payment_obj.gateway_response = result.raw_response

        payment_obj.save()

        # Refresh in-memory object
        payment.status = payment_obj.status
        payment.gateway_txn_id = payment_obj.gateway_txn_id
        payment.failure_reason = payment_obj.failure_reason
        payment.error_code = payment_obj.error_code

    def _fail_payment(self, payment: Payment, error_code: str, message: str):
        Payment.objects.filter(id=payment.id).update(
            status='failed',
            error_code=error_code,
            failure_reason=message,
            failed_at=timezone.now(),
        )
        payment.status = 'failed'