import logging

import razorpay
from django.conf import settings

from payments.processors.base import PaymentProcessor, PaymentResult

logger = logging.getLogger(__name__)


class RazorpayGateway(PaymentProcessor):
    """
    Razorpay sandbox gateway.
    Used for real card/UPI/netbanking flows in test mode.
    Test cards:
      4111111111111111 → success
      4000000000000002 → decline
      4000000000003220 → 3DS required
    """

    def __init__(self):
        self.client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )

    def authorize(self, payment, payment_data: dict) -> PaymentResult:
        try:
            # Create Razorpay order first
            razorpay_order = self.client.order.create({
                'amount': payment.amount,
                'currency': payment.currency,
                'receipt': str(payment.order_id),
                'payment_capture': 0,  # Manual capture
            })

            return PaymentResult(
                success=True,
                status='authorized',
                gateway_txn_id=razorpay_order['id'],
                raw_response=razorpay_order,
            )

        except razorpay.errors.BadRequestError as e:
            logger.error(f"Razorpay bad request: {e}")
            return PaymentResult(
                success=False,
                status='failed',
                error_code='GATEWAY_BAD_REQUEST',
                error_message=str(e),
            )
        except Exception as e:
            logger.error(f"Razorpay error: {e}")
            return PaymentResult(
                success=False,
                status='failed',
                error_code='GATEWAY_ERROR',
                error_message='Payment gateway error. Please retry.',
            )

    def capture(self, payment, amount: int) -> PaymentResult:
        try:
            response = self.client.payment.capture(
                payment.gateway_txn_id,
                amount,
                {'currency': payment.currency}
            )
            return PaymentResult(
                success=True,
                status='captured',
                gateway_txn_id=response['id'],
                raw_response=response,
            )
        except Exception as e:
            logger.error(f"Razorpay capture error: {e}")
            return PaymentResult(
                success=False,
                status='failed',
                error_code='CAPTURE_FAILED',
                error_message=str(e),
            )

    def refund(self, payment, amount: int) -> PaymentResult:
        try:
            response = self.client.payment.refund(
                payment.gateway_txn_id,
                {'amount': amount}
            )
            return PaymentResult(
                success=True,
                status='refunded',
                gateway_txn_id=response['id'],
                raw_response=response,
            )
        except Exception as e:
            logger.error(f"Razorpay refund error: {e}")
            return PaymentResult(
                success=False,
                status='failed',
                error_code='REFUND_FAILED',
                error_message=str(e),
            )

    def check_status(self, gateway_txn_id: str) -> PaymentResult:
        try:
            response = self.client.payment.fetch(gateway_txn_id)
            status_map = {
                'authorized': 'authorized',
                'captured': 'captured',
                'failed': 'failed',
                'refunded': 'refunded',
            }
            return PaymentResult(
                success=response['status'] in ('authorized', 'captured'),
                status=status_map.get(response['status'], 'failed'),
                gateway_txn_id=gateway_txn_id,
                raw_response=response,
            )
        except Exception as e:
            return PaymentResult(
                success=False,
                status='failed',
                error_code='STATUS_CHECK_FAILED',
                error_message=str(e),
            )
