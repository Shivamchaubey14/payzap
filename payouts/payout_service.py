import uuid
import re
import logging
from django.utils import timezone
from payouts.models import Payout

logger = logging.getLogger(__name__)

DAILY_PAYOUT_LIMIT = 10_000_000  # ₹1,00,000 in paise per merchant per day


def _validate_ifsc(ifsc: str) -> bool:
    return bool(re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', ifsc))


def _validate_account_number(account: str) -> bool:
    return bool(re.match(r'^\d{9,18}$', account))


def _validate_upi_id(upi_id: str) -> bool:
    return bool(re.match(r'^[\w.\-]+@[\w]+$', upi_id))


def _check_daily_limit(merchant, amount: int):
    from django.db.models import Sum
    from django.utils import timezone as tz
    now = tz.localtime(tz.now())
    today = now.date()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total_today = Payout.objects.filter(
        merchant=merchant,
        created_at__gte=start_of_day,
        status__in=('queued', 'processing', 'processed'),
    ).aggregate(total=Sum('amount'))['total'] or 0

    if total_today + amount > DAILY_PAYOUT_LIMIT:
        raise ValueError(
            f'Daily payout limit exceeded. '
            f'Used: ₹{total_today/100:.2f}, '
            f'Limit: ₹{DAILY_PAYOUT_LIMIT/100:.2f}'
        )


def create_payout(merchant, data: dict) -> Payout:
    """Validate and create a single payout record."""
    amount = data['amount']
    mode = data.get('mode', 'IMPS').upper()

    if amount <= 0:
        raise ValueError('Amount must be greater than zero.')

    _check_daily_limit(merchant, amount)

    # Mode-specific validation
    if mode == 'UPI':
        upi_id = data.get('upi_id', '')
        if not upi_id:
            raise ValueError('upi_id is required for UPI payouts.')
        if not _validate_upi_id(upi_id):
            raise ValueError(f'Invalid UPI ID format: {upi_id}')
    else:
        account_number = data.get('account_number', '')
        ifsc = data.get('ifsc', '')
        if not account_number:
            raise ValueError('account_number is required for NEFT/IMPS payouts.')
        if not ifsc:
            raise ValueError('ifsc is required for NEFT/IMPS payouts.')
        if not _validate_account_number(account_number):
            raise ValueError('Invalid account number. Must be 9-18 digits.')
        if not _validate_ifsc(ifsc):
            raise ValueError(f'Invalid IFSC format: {ifsc}')

    payout = Payout.objects.create(
        merchant=merchant,
        amount=amount,
        mode=mode,
        purpose=data.get('purpose', 'payout'),
        beneficiary_name=data['beneficiary_name'],
        account_number=data.get('account_number', ''),
        ifsc=data.get('ifsc', ''),
        upi_id=data.get('upi_id', ''),
        reference_id=data.get('reference_id', ''),
        status='queued',
    )

    return payout


def process_payout(payout_id: str):
    """
    Mock bank payout processor.
    In production this calls NEFT/IMPS/UPI bank API.
    """
    try:
        payout = Payout.objects.get(id=payout_id)
    except Payout.DoesNotExist:
        logger.error(f'Payout {payout_id} not found.')
        return

    Payout.objects.filter(id=payout_id).update(status='processing')

    # Mock: always succeeds
    utr = f"UTR{timezone.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"

    Payout.objects.filter(id=payout_id).update(
        status='processed',
        utr_number=utr,
        processed_at=timezone.now(),
    )

    payout.refresh_from_db()
    logger.info(f'Payout {payout_id} processed — UTR: {utr}')

    # Fire webhook
    from webhooks.tasks import dispatch_webhook_event
    dispatch_webhook_event.delay(
        str(payout.merchant_id),
        'payout.processed',
        {
            'payout_id': str(payout.id),
            'amount': payout.amount,
            'utr_number': utr,
            'mode': payout.mode,
            'beneficiary_name': payout.beneficiary_name,
        }
    )