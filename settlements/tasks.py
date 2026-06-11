import logging

from celery import shared_task
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name='settlements.process_daily_settlements')
def process_daily_settlements():
    """
    Runs at 11 PM daily via Celery Beat.
    For each merchant: SUM(captured) - SUM(refunds) - platform_fee = net_payout
    Creates Settlement batch records and initiates bank payouts.
    """
    from merchants.models import Merchant
    from payments.models import Payment
    from settlements.models import Settlement

    settlement_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    settlement_to = timezone.now()

    merchants = Merchant.objects.filter(is_active=True, is_live=True, kyc_status='approved')
    logger.info(f"Starting daily settlement for {merchants.count()} merchants")

    for merchant in merchants:
        try:
            # Get all captured payments not yet settled
            payments = Payment.objects.filter(
                order__merchant=merchant,
                status='captured',
                in_settlement=False,
            )

            if not payments.exists():
                continue

            gross_amount = payments.aggregate(total=Sum('amount'))['total'] or 0
            total_refunded = payments.aggregate(total=Sum('amount_refunded'))['total'] or 0
            net_amount = gross_amount - total_refunded

            # Deduct platform fee
            fee = int(net_amount * float(merchant.fee_rate))
            payout_amount = net_amount - fee

            if payout_amount <= 0:
                continue

            # Create settlement record
            settlement = Settlement.objects.create(
                merchant=merchant,
                amount=payout_amount,
                fees=fee,
                settlement_from=settlement_from,
                settlement_to=settlement_to,
                status='processing',
                bank_account_number=merchant.bank_account_number,
                bank_ifsc=merchant.bank_ifsc,
            )

            # Initiate bank payout (mock for now)
            _initiate_bank_payout(settlement)
            # Mark payments as in settlement
            payments.update(in_settlement=True)

            logger.info(
                f"Settlement {settlement.id} created for merchant "
                f"{merchant.email}: ₹{payout_amount/100:.2f}"
            )

        except Exception as e:
            logger.error(f"Settlement failed for merchant {merchant.email}: {e}")

    logger.info("Daily settlement run complete")


def _initiate_bank_payout(settlement):
    """
    Mock bank payout — in production this calls NEFT/IMPS API.
    Simulates instant success for development.
    """
    import uuid

    from settlements.models import Settlement

    # Simulate bank UTR number
    utr = f"UTR{timezone.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"

    Settlement.objects.filter(id=settlement.id).update(
        status='processed',
        utr_number=utr,
        settled_at=timezone.now(),
    )

    # Fire webhook to merchant
    from webhooks.tasks import dispatch_webhook_event
    dispatch_webhook_event.delay(
        str(settlement.merchant_id),
        'settlement.processed',
        {
            'settlement_id': str(settlement.id),
            'amount': settlement.amount,
            'utr_number': utr,
        }
    )
