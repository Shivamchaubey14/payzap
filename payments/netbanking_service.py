import hashlib
import hmac
import logging
import uuid

from django.db import transaction
from django.utils import timezone

from payments.models import Bank, Order, Payment

logger = logging.getLogger(__name__)

NETBANKING_REDIRECT_BASE = 'https://mock-bank.payzap.test/netbanking'


class NetBankingService:
    """
    Net banking redirect flow:
    1. Merchant calls POST /v1/payments/ with method=netbanking + bank_code
    2. PayZap creates payment, generates signed redirect URL to bank login page
    3. Customer logs in at bank, authorises payment
    4. Bank redirects back to PayZap callback URL with result
    5. PayZap verifies HMAC signature, updates payment status
    6. PayZap redirects customer back to merchant return URL
    """

    SECRET = b'payzap_netbanking_secret'

    def process_netbanking(self, order: Order, bank_code: str) -> Payment:
        # Validate bank code
        try:
            bank = Bank.objects.get(code=bank_code.upper(), is_active=True)
        except Bank.DoesNotExist:
            payment = Payment.objects.create(
                order=order,
                method='netbanking',
                amount=order.amount,
                currency=order.currency,
                status='failed',
                error_code='INVALID_BANK',
                failure_reason=f'Bank code {bank_code} not supported.',
            )
            return payment

        # Create payment record
        payment = Payment.objects.create(
            order=order,
            method='netbanking',
            amount=order.amount,
            currency=order.currency,
            bank_code=bank.code,
            bank_name=bank.name,
            status='processing',
        )

        Order.objects.filter(id=order.id).update(status='attempted')

        # Generate signed redirect URL
        redirect_url = self._generate_redirect_url(payment, bank)
        Payment.objects.filter(id=payment.id).update(netbanking_url=redirect_url)
        payment.netbanking_url = redirect_url

        logger.info(f"NetBanking redirect created for payment {payment.id} → {bank.name}")
        return payment

    def _generate_redirect_url(self, payment, bank) -> str:
        """Generate HMAC-signed redirect URL to bank login page."""
        txn_ref = uuid.uuid4().hex[:16]
        callback = "https://api.payzap.test/v1/payments/netbanking/callback/"
        data = f"{payment.id}:{payment.amount}:{txn_ref}"
        sig = hmac.new(self.SECRET, data.encode(), hashlib.sha256).hexdigest()
        return (
            f"{NETBANKING_REDIRECT_BASE}"
            f"?bank={bank.gateway_code}"
            f"&amount={payment.amount}"
            f"&txn_ref={txn_ref}"
            f"&payment_id={payment.id}"
            f"&callback={callback}"
            f"&sig={sig}"
        )

    def handle_callback(self, payment_id: str, status: str, sig: str,
                        txn_ref: str) -> Payment:
        """
        Called when bank redirects back after customer authentication.
        Verifies HMAC signature before updating payment state.
        """
        try:
            payment = Payment.objects.select_related('order').get(id=payment_id)
        except Payment.DoesNotExist:
            raise ValueError(f'Payment {payment_id} not found.') from None

        # Verify signature
        data = f"{payment_id}:{payment.amount}:{txn_ref}"
        expected_sig = hmac.new(self.SECRET, data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            raise ValueError('Invalid callback signature.')

        gateway_txn_id = f"mock_nb_{uuid.uuid4().hex[:12]}"

        with transaction.atomic():
            if status == 'success':
                Payment.objects.filter(id=payment.id).update(
                    status='authorized',
                    gateway_txn_id=gateway_txn_id,
                )
                payment.status = 'authorized'
            else:
                Payment.objects.filter(id=payment.id).update(
                    status='failed',
                    error_code='NETBANKING_FAILED',
                    failure_reason='Customer cancelled or bank declined.',
                    failed_at=timezone.now(),
                )
                payment.status = 'failed'

        return payment
