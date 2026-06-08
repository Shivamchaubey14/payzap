import uuid
import random
import time
from payments.processors.base import PaymentProcessor, PaymentResult


class MockBankGateway(PaymentProcessor):
    """
    Simulates bank gateway responses for development and testing.
    Uses card number patterns to simulate different scenarios:
      4111111111111111 → success (authorize + capture)
      4000000000000002 → decline
      4000000000003220 → 3DS required
      4000000000000119 → timeout / network error
    """

    # Simulated processing delay (ms) — set to 0 in tests
    PROCESSING_DELAY = 0.1

    def authorize(self, payment, payment_data: dict) -> PaymentResult:
        time.sleep(self.PROCESSING_DELAY)
        card_number = payment_data.get('card_number', '')
        scenario = self._get_scenario(card_number)
        gateway_txn_id = f"mock_auth_{uuid.uuid4().hex[:12]}"

        if scenario == 'success':
            return PaymentResult(
                success=True,
                status='authorized',
                gateway_txn_id=gateway_txn_id,
                raw_response={
                    'txn_id': gateway_txn_id,
                    'auth_code': f"AUTH{random.randint(100000, 999999)}",
                    'message': 'Authorization successful',
                }
            )

        elif scenario == 'decline':
            return PaymentResult(
                success=False,
                status='failed',
                gateway_txn_id=gateway_txn_id,
                error_code='CARD_DECLINED',
                error_message='Your card was declined.',
                raw_response={
                    'txn_id': gateway_txn_id,
                    'message': 'Insufficient funds or card blocked',
                }
            )

        elif scenario == '3ds_required':
            return PaymentResult(
                success=False,
                status='pending_3ds',
                gateway_txn_id=gateway_txn_id,
                error_code='3DS_REQUIRED',
                error_message='3D Secure authentication required.',
                raw_response={
                    'txn_id': gateway_txn_id,
                    'acs_url': 'https://mock-bank.test/3ds/authenticate',
                    'message': '3DS authentication required',
                }
            )

        elif scenario == 'timeout':
            time.sleep(0.5)
            return PaymentResult(
                success=False,
                status='failed',
                gateway_txn_id=gateway_txn_id,
                error_code='GATEWAY_TIMEOUT',
                error_message='Gateway timed out. Please retry.',
                raw_response={'message': 'Connection timeout'},
            )

        # Default — random success/fail for unlisted cards
        return self._random_result(gateway_txn_id)

    def capture(self, payment, amount: int) -> PaymentResult:
        time.sleep(self.PROCESSING_DELAY)

        # Can only capture authorized payments
        if payment.status != 'authorized':
            return PaymentResult(
                success=False,
                status='failed',
                error_code='INVALID_STATE',
                error_message=f'Cannot capture payment in {payment.status} state.',
            )

        if amount > payment.amount:
            return PaymentResult(
                success=False,
                status='failed',
                error_code='AMOUNT_EXCEEDS_AUTHORIZED',
                error_message='Capture amount exceeds authorized amount.',
            )

        gateway_txn_id = f"mock_cap_{uuid.uuid4().hex[:12]}"
        return PaymentResult(
            success=True,
            status='captured',
            gateway_txn_id=gateway_txn_id,
            raw_response={
                'txn_id': gateway_txn_id,
                'captured_amount': amount,
                'message': 'Payment captured successfully',
            }
        )

    def refund(self, payment, amount: int) -> PaymentResult:
        time.sleep(self.PROCESSING_DELAY)

        if payment.status not in ('captured', 'partially_refunded'):
            return PaymentResult(
                success=False,
                status='failed',
                error_code='INVALID_STATE',
                error_message=f'Cannot refund payment in {payment.status} state.',
            )

        if amount > payment.refundable_amount:
            return PaymentResult(
                success=False,
                status='failed',
                error_code='REFUND_AMOUNT_EXCEEDS_CAPTURED',
                error_message='Refund amount exceeds refundable amount.',
            )

        gateway_txn_id = f"mock_ref_{uuid.uuid4().hex[:12]}"
        return PaymentResult(
            success=True,
            status='refunded',
            gateway_txn_id=gateway_txn_id,
            raw_response={
                'txn_id': gateway_txn_id,
                'refunded_amount': amount,
                'message': 'Refund processed successfully',
            }
        )

    def check_status(self, gateway_txn_id: str) -> PaymentResult:
        time.sleep(self.PROCESSING_DELAY)
        return PaymentResult(
            success=True,
            status='captured',
            gateway_txn_id=gateway_txn_id,
            raw_response={'message': 'Payment completed'},
        )

    def _get_scenario(self, card_number: str) -> str:
        card_number = card_number.replace(' ', '')
        scenarios = {
            '4111111111111111': 'success',
            '4000000000000002': 'decline',
            '4000000000003220': '3ds_required',
            '4000000000000119': 'timeout',
        }
        return scenarios.get(card_number, 'random')

    def _random_result(self, gateway_txn_id: str) -> PaymentResult:
        if random.random() > 0.2:  # 80% success
            return PaymentResult(
                success=True,
                status='authorized',
                gateway_txn_id=gateway_txn_id,
                raw_response={'message': 'Authorized'},
            )
        return PaymentResult(
            success=False,
            status='failed',
            error_code='GENERIC_DECLINE',
            error_message='Payment declined.',
            raw_response={'message': 'Declined'},
        )