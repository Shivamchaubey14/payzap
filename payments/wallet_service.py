import logging
import uuid

from django.db import transaction
from django.utils import timezone

from payments.models import Order, Payment

logger = logging.getLogger(__name__)

SUPPORTED_WALLETS = {
    'paytm':     {'name': 'PayTM',       'min_amount': 100},
    'phonepe':   {'name': 'PhonePe',     'min_amount': 100},
    'amazonpay': {'name': 'Amazon Pay',  'min_amount': 100},
    'mobikwik':  {'name': 'MobiKwik',    'min_amount': 100},
    'freecharge': {'name': 'FreeCharge', 'min_amount': 100},
}


class WalletService:
    """
    Wallet payment flow:
    1. Validate wallet provider is supported
    2. Check minimum amount
    3. Call wallet partner SDK (mocked here)
    4. Return authorized or failed payment
    """

    def process_wallet_payment(self, order: Order, wallet_provider: str) -> Payment:
        provider = wallet_provider.lower().strip()

        # Validate provider
        if provider not in SUPPORTED_WALLETS:
            payment = Payment.objects.create(
                order=order,
                method='wallet',
                amount=order.amount,
                currency=order.currency,
                status='failed',
                error_code='UNSUPPORTED_WALLET',
                failure_reason=f'Wallet {wallet_provider} is not supported.',
            )
            return payment

        wallet_info = SUPPORTED_WALLETS[provider]

        # Check minimum amount
        if order.amount < wallet_info['min_amount']:
            payment = Payment.objects.create(
                order=order,
                method='wallet',
                amount=order.amount,
                currency=order.currency,
                status='failed',
                error_code='AMOUNT_TOO_LOW',
                failure_reason=f'Minimum amount for {wallet_info["name"]} is '
                               f'₹{wallet_info["min_amount"] / 100}.',
            )
            return payment

        # Create payment record
        payment = Payment.objects.create(
            order=order,
            method='wallet',
            amount=order.amount,
            currency=order.currency,
            wallet_provider=provider,
            status='processing',
        )

        Order.objects.filter(id=order.id).update(status='attempted')

        # Call wallet SDK (mocked)
        result = self._call_wallet_sdk(provider, payment)

        gateway_txn_id = f"mock_wallet_{uuid.uuid4().hex[:12]}"

        with transaction.atomic():
            if result['success']:
                Payment.objects.filter(id=payment.id).update(
                    status='authorized',
                    gateway_txn_id=gateway_txn_id,
                    wallet_txn_id=result['wallet_txn_id'],
                )
                payment.status = 'authorized'
            else:
                Payment.objects.filter(id=payment.id).update(
                    status='failed',
                    error_code=result['error_code'],
                    failure_reason=result['error_message'],
                    failed_at=timezone.now(),
                )
                payment.status = 'failed'

        payment.refresh_from_db()
        logger.info(
            f"Wallet payment {payment.id} via {wallet_info['name']}: {payment.status}"
        )
        return payment

    def _call_wallet_sdk(self, provider: str, payment) -> dict:
        """
        Mock wallet SDK call.
        In production: call PayTM/PhonePe/AmazonPay partner API.
        """
        # Simulate insufficient balance for mobikwik in tests
        if provider == 'mobikwik':
            return {
                'success': False,
                'error_code': 'INSUFFICIENT_WALLET_BALANCE',
                'error_message': 'Insufficient balance in MobiKwik wallet.',
                'wallet_txn_id': '',
            }

        return {
            'success': True,
            'wallet_txn_id': f"wtxn_{uuid.uuid4().hex[:16]}",
            'error_code': '',
            'error_message': '',
        }
