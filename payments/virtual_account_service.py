import uuid
import logging
from django.utils import timezone
from django.db import transaction
from payments.models import VirtualAccount, Payment, Order
from merchants.models import Merchant
from webhooks.webhook_service import WebhookService

logger = logging.getLogger(__name__)


class VirtualAccountService:

    def create_virtual_account(self, merchant: Merchant, data: dict) -> VirtualAccount:
        """Create a virtual account with a unique UPI ID and account number."""
        ref = uuid.uuid4().hex[:10]
        virtual_upi_id = f"payzap.va.{ref}@payzap"
        virtual_account_number = f"PAYZ{ref.upper()[:12]}"

        va = VirtualAccount.objects.create(
            merchant=merchant,
            name=data.get('name', 'Virtual Account'),
            description=data.get('description', ''),
            virtual_upi_id=virtual_upi_id,
            virtual_account_number=virtual_account_number,
            amount_expected=data.get('amount_expected'),
            close_by=data.get('close_by'),
            notes=data.get('notes', {}),
        )
        logger.info(f"VirtualAccount {va.id} created — UPI: {va.virtual_upi_id}")
        return va

    @transaction.atomic
    def record_credit(self, va: VirtualAccount, amount: int,
                      payment_method: str = 'upi') -> Payment:
        """
        Called when money lands on a virtual account (bank callback / mock).
        Creates an Order + Payment, fires webhook.
        """
        if va.status != 'active':
            raise ValueError('Virtual account is closed.')

        # Create order
        order = Order.objects.create(
            merchant=va.merchant,
            amount=amount,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
            status='paid',
            notes={'virtual_account_id': str(va.id)},
        )

        # Create payment
        payment = Payment.objects.create(
            order=order,
            method=payment_method,
            amount=amount,
            currency='INR',
            status='captured',
            captured_at=timezone.now(),
            gateway_txn_id=f'va_credit_{uuid.uuid4().hex[:12]}',
        )

        # Update VA amount_paid
        VirtualAccount.objects.filter(id=va.id).update(
            amount_paid=va.amount_paid + amount
        )

        # Auto-close if expected amount fully received
        va.refresh_from_db()
        if va.amount_expected and va.amount_paid >= va.amount_expected:
            VirtualAccount.objects.filter(id=va.id).update(
                status='closed',
                closed_at=timezone.now(),
            )

        # Fire webhook
        try:
            webhook_service = WebhookService()
            webhook_service.dispatch_event(
                merchant=va.merchant,
                event_type='virtual_account.credited',
                payload={
                    'virtual_account_id': str(va.id),
                    'payment_id':         str(payment.id),
                    'amount':             amount,
                    'method':             payment_method,
                },
            )
        except Exception as e:
            logger.warning(f"Webhook dispatch failed for VA credit: {e}")

        va.refresh_from_db()
        logger.info(f"VA {va.id} credited ₹{amount/100:.2f} — payment {payment.id}")
        return payment

    def close_account(self, va: VirtualAccount, merchant: Merchant) -> VirtualAccount:
        if va.merchant != merchant:
            raise ValueError('Permission denied.')
        VirtualAccount.objects.filter(id=va.id).update(
            status='closed',
            closed_at=timezone.now(),
        )
        va.refresh_from_db()
        return va