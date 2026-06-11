import logging
import uuid

from django.db import transaction
from django.utils import timezone

from payments.models import Payment, Refund

logger = logging.getLogger(__name__)


class RefundService:
    """
    Handles full and partial refunds.
    Rules:
      - Payment must be in 'captured' or 'authorized' status
      - Total refunded amount cannot exceed captured amount
      - Each refund is atomic — no double-refund via DB lock
    """

    def initiate_refund(self, payment: Payment, amount: int,
                        reason: str = '', notes: dict = None) -> Refund:
        """
        Main entry point. Creates and processes a refund.
        amount is in paise.
        """
        notes = notes or {}

        # Validate payment is refundable
        if payment.status not in ('captured','partially_refunded'):
            raise ValueError(
                f'Payment {payment.id} cannot be refunded '
                f'(status: {payment.status}). Only captured or authorized payments are refundable.'
            )

        # Validate amount
        if amount <= 0:
            raise ValueError('Refund amount must be greater than zero.')

        if amount > payment.refundable_amount:
            raise ValueError(
                f'Refund amount ₹{amount/100:.2f} exceeds '
                f'refundable amount ₹{payment.refundable_amount/100:.2f}.'
            )

        # Create refund record
        refund = Refund.objects.create(
            payment=payment,
            amount=amount,
            currency=payment.currency,
            status='initiated',
            reason=reason,
            notes=notes,
            initiated_by='merchant',
        )

        # Process it
        return self._process_refund(refund, payment)

    @transaction.atomic
    def _process_refund(self, refund: Refund, payment: Payment) -> Refund:
        """
        Atomically process the refund and update payment's amount_refunded.
        Uses select_for_update to prevent concurrent refund race conditions.
        """
        # Lock the payment row
        payment_locked = Payment.objects.select_for_update().get(id=payment.id)

        # Re-validate under lock (another refund might have gone through)
        if refund.amount > payment_locked.refundable_amount:
            Refund.objects.filter(id=refund.id).update(
                status='failed',
                failure_reason='Refund amount exceeds refundable amount after lock.',
            )
            refund.refresh_from_db()
            return refund

        # Update refund status to processing
        Refund.objects.filter(id=refund.id).update(status='processing')

        # Call gateway (mocked)
        gateway_refund_id = f"rfnd_{uuid.uuid4().hex[:16]}"
        gateway_success = True  # mock always succeeds

        if gateway_success:
            new_amount_refunded = payment_locked.amount_refunded + refund.amount

            # Determine new payment status
            if new_amount_refunded >= payment_locked.amount:
                new_payment_status = 'refunded'
            else:
                new_payment_status = 'partially_refunded'

            # Update payment
            Payment.objects.filter(id=payment.id).update(
                amount_refunded=new_amount_refunded,
                status=new_payment_status,
            )

            # Update refund
            Refund.objects.filter(id=refund.id).update(
                status='processed',
                gateway_refund_id=gateway_refund_id,
                processed_at=timezone.now(),
            )

            logger.info(
                f"Refund {refund.id} processed — "
                f"₹{refund.amount/100:.2f} refunded on payment {payment.id}"
            )
        else:
            Refund.objects.filter(id=refund.id).update(
                status='failed',
                failure_reason='Gateway refund failed.',
            )

        refund.refresh_from_db()
        return refund

    def get_refund(self, refund_id: str, merchant) -> Refund:
        """Fetch a refund, enforcing merchant ownership."""
        try:
            return Refund.objects.select_related('payment__order__merchant').get(
                id=refund_id,
                payment__order__merchant=merchant,
            )
        except Refund.DoesNotExist:
            raise ValueError('Refund not found.') from None
