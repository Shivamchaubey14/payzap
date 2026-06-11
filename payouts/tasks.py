import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='payouts.process_payout')
def process_payout_task(payout_id: str):
    from payouts.payout_service import process_payout
    process_payout(payout_id)


@shared_task(name='payouts.process_bulk_payout')
def process_bulk_payout_task(batch_id: str, merchant_id: str, rows: list):
    """Process each row in a bulk payout batch."""
    from merchants.models import Merchant
    from payouts.models import Payout
    from payouts.payout_service import create_payout, process_payout

    try:
        merchant = Merchant.objects.get(id=merchant_id)
    except Merchant.DoesNotExist:
        logger.error(f'Merchant {merchant_id} not found for bulk payout.')
        return

    for row in rows:
        try:
            payout = create_payout(merchant, {**row, 'batch_id': batch_id})
            Payout.objects.filter(id=payout.id).update(batch_id=batch_id)
            process_payout(str(payout.id))
        except Exception as e:
            logger.error(f'Bulk payout row failed for {row}: {e}')
