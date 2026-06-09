import logging
from django.db import transaction
from django.utils import timezone
from payments.models import Order, Payment
from payments.bin_lookup import lookup_bin, get_gateway_for_network
from payments.processors.mock_gateway import MockBankGateway

logger = logging.getLogger(__name__)


class CardPaymentService:
    """
    Handles card-specific payment logic:
    - BIN lookup and network detection
    - Sanctioned BIN blocking
    - 3DS2 flow handling
    - Network-based gateway routing
    - Card tokenization (stores last4 and network, never raw PAN)
    """

    def process_card_payment(self, order: Order, card_data: dict) -> Payment:
        card_number = card_data.get('card_number', '')

        # Step 1 — BIN lookup
        bin_info = lookup_bin(card_number)
        logger.info(f"BIN lookup for order {order.id}: {bin_info['network']} / {bin_info['bank']}")

        # Step 2 — Block sanctioned BINs
        if bin_info.get('is_sanctioned'):
            payment = Payment.objects.create(
                order=order,
                method='card',
                amount=order.amount,
                currency=order.currency,
                status='failed',
                error_code='BIN_BLACKLISTED',
                failure_reason='Card BIN is from a sanctioned region.',
                card_network=bin_info['network'],
            )
            return payment

        # Step 3 — Tokenize card (store only last4 and network — never raw PAN)
        card_last4 = card_number[-4:] if len(card_number) >= 4 else '****'
        card_token = self._tokenize_card(card_number)

        # Step 4 — Route to correct gateway
        gateway_name = get_gateway_for_network(bin_info['network'])
        gateway = self._get_gateway(gateway_name)

        # Step 5 — Create payment record
        payment = Payment.objects.create(
            order=order,
            method='card',
            amount=order.amount,
            currency=order.currency,
            card_network=bin_info['network'],
            card_last4=card_last4,
            card_token=card_token,
            bank=bin_info['bank'],
        )

        # Step 6 — Update order status
        Order.objects.filter(id=order.id).update(status='attempted')

        # Step 7 — Call gateway
        result = gateway.authorize(payment, card_data)

        # Step 8 — Handle 3DS requirement
        if result.error_code == '3DS_REQUIRED':
            with transaction.atomic():
                Payment.objects.filter(id=payment.id).update(
                    status='processing',
                    is_3ds=True,
                    three_ds_url=result.raw_response.get('acs_url', ''),
                    gateway_txn_id=result.gateway_txn_id,
                )
                payment.status = 'processing'
                payment.is_3ds = True
                payment.three_ds_url = result.raw_response.get('acs_url', '')
            return payment

        # Step 9 — Update final state
        with transaction.atomic():
            update_data = {
                'gateway_txn_id': result.gateway_txn_id,
                'gateway_response': result.raw_response,
            }
            if result.success:
                update_data['status'] = result.status
                if result.status == 'captured':
                    update_data['captured_at'] = timezone.now()
                    Order.objects.filter(id=order.id).update(status='paid')
            else:
                update_data['status'] = 'failed'
                update_data['error_code'] = result.error_code
                update_data['failure_reason'] = result.error_message
                update_data['failed_at'] = timezone.now()

            Payment.objects.filter(id=payment.id).update(**update_data)
            payment.status = update_data['status']
            payment.error_code = result.error_code if not result.success else ''

        return payment

    def _tokenize_card(self, card_number: str) -> str:
        """
        In production: send PAN to Stripe Vault or HSM, receive token.
        Here we simulate tokenization — never store raw PAN.
        """
        import hashlib
        return 'tok_' + hashlib.sha256(card_number.encode()).hexdigest()[:24]

    def _get_gateway(self, gateway_name: str):
        """Return the correct gateway instance based on routing."""
        if gateway_name == 'razorpay':
            try:
                from django.conf import settings
                if hasattr(settings, 'RAZORPAY_KEY_ID') and settings.RAZORPAY_KEY_ID:
                    from payments.processors.razorpay_gateway import RazorpayGateway
                    return RazorpayGateway()
            except Exception:
                pass
        return MockBankGateway()