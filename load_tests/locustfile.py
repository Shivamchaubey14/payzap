"""
PayZap 100k TPS Load Test
Simulates the full payment lifecycle: create order → process payment → check status
"""
import random
import uuid
from locust import HttpUser, TaskSet, task, between, events
from locust.runners import MasterRunner, WorkerRunner


# ── Test card numbers ──────────────────────────────────────────────────────────
CARD_SUCCESS   = '4111111111111111'
CARD_DECLINE   = '4000000000000002'
CARD_3DS       = '4000000000003220'

CURRENCIES     = ['INR']
BANKS          = ['HDFC', 'SBI', 'ICICI', 'AXIS', 'KOTAK']
UPI_VPAS       = ['test@upi', 'load@payzap', 'perf@test']


def make_auth_header(api_key: str) -> dict:
    return {'X-API-KEY': api_key}


# ── Task sets ─────────────────────────────────────────────────────────────────

class CardPaymentFlow(TaskSet):
    """Create order → card payment → capture (happy path, 70% of traffic)"""

    @task(7)
    def full_card_payment(self):
        api_key = self.user.api_key
        headers = make_auth_header(api_key)
        idempotency_key = uuid.uuid4().hex

        # Step 1 — create order
        with self.client.post(
            '/v1/orders/',
            json={
                'amount': random.randint(10000, 500000),
                'currency': 'INR',
                'receipt': f'load_test_{idempotency_key[:8]}',
            },
            headers={**headers, 'Idempotency-Key': idempotency_key},
            name='/v1/orders/ [create]',
            catch_response=True,
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f'Order creation failed: {resp.status_code}')
                return
            order_id = resp.json().get('id')

        if not order_id:
            return

        # Step 2 — process payment
        with self.client.post(
            '/v1/payments/',
            json={
                'order_id': order_id,
                'method': 'card',
                'card_number': CARD_SUCCESS,
                'card_expiry': '12/26',
                'card_cvv': '123',
                'card_holder': 'Load Test User',
            },
            headers=headers,
            name='/v1/payments/ [card]',
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 201):
                resp.failure(f'Payment failed: {resp.status_code}')
                return
            payment_id = resp.json().get('id')

        if not payment_id:
            return

        # Step 3 — capture
        with self.client.post(
            f'/v1/payments/{payment_id}/capture/',
            headers=headers,
            name='/v1/payments/{id}/capture/',
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 201):
                resp.failure(f'Capture failed: {resp.status_code}')

    @task(2)
    def declined_card(self):
        """Simulate decline flow — 20% of card traffic"""
        headers = make_auth_header(self.user.api_key)
        idempotency_key = uuid.uuid4().hex

        with self.client.post(
            '/v1/orders/',
            json={'amount': 50000, 'currency': 'INR', 'receipt': 'decline_test'},
            headers={**headers, 'Idempotency-Key': idempotency_key},
            name='/v1/orders/ [create]',
            catch_response=True,
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f'Order creation failed: {resp.status_code}')
                return
            order_id = resp.json().get('id')

        self.client.post(
            '/v1/payments/',
            json={
                'order_id': order_id,
                'method': 'card',
                'card_number': CARD_DECLINE,
                'card_expiry': '12/26',
                'card_cvv': '123',
                'card_holder': 'Declined User',
            },
            headers=headers,
            name='/v1/payments/ [decline]',
        )

    @task(1)
    def get_order_status(self):
        """Poll order status — 10% of card traffic"""
        headers = make_auth_header(self.user.api_key)
        fake_id = uuid.uuid4()
        self.client.get(
            f'/v1/orders/{fake_id}/',
            headers=headers,
            name='/v1/orders/{id}/ [get]',
        )


class UPIPaymentFlow(TaskSet):
    """UPI collect flow"""

    @task
    def upi_payment(self):
        headers = make_auth_header(self.user.api_key)
        idempotency_key = uuid.uuid4().hex

        with self.client.post(
            '/v1/orders/',
            json={'amount': random.randint(5000, 100000), 'currency': 'INR', 'receipt': 'upi_load'},
            headers={**headers, 'Idempotency-Key': idempotency_key},
            name='/v1/orders/ [create]',
            catch_response=True,
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f'Order creation failed: {resp.status_code}')
                return
            order_id = resp.json().get('id')

        self.client.post(
            '/v1/payments/',
            json={
                'order_id': order_id,
                'method': 'upi',
                'upi_vpa': random.choice(UPI_VPAS),
            },
            headers=headers,
            name='/v1/payments/ [upi]',
        )


class ReadOnlyFlow(TaskSet):
    """Health checks and status polling — low-cost background traffic"""

    @task(5)
    def health_check(self):
        self.client.get('/monitoring/health/', name='/monitoring/health/')

    @task(3)
    def list_settlements(self):
        self.client.get(
            '/v1/settlements/',
            headers=make_auth_header(self.user.api_key),
            name='/v1/settlements/ [list]',
        )

    @task(2)
    def list_payouts(self):
        self.client.get(
            '/v1/payouts/',
            headers=make_auth_header(self.user.api_key),
            name='/v1/payouts/ [list]',
        )


# ── User classes ──────────────────────────────────────────────────────────────

class MerchantUser(HttpUser):
    """
    Represents a merchant hitting the payment API.
    Mix: 70% card, 20% UPI, 10% read-only.
    """
    wait_time = between(0.1, 0.5)
    tasks = {
        CardPaymentFlow: 7,
        UPIPaymentFlow:  2,
        ReadOnlyFlow:    1,
    }

    def on_start(self):
        # In a real test, rotate through real test API keys
        # For local testing, use your test key from .env
        self.api_key = 'rzp_test_kpJyPWio_oyI0lm0Y7_xQgeUXB3v8qfqvM5NGEGjuBn0'


class HighFrequencyUser(HttpUser):
    """
    Simulates high-frequency merchant — minimal wait, card only.
    Used to stress-test peak TPS.
    """
    wait_time = between(0.01, 0.05)
    tasks = {CardPaymentFlow: 1}
    weight = 1  # spawn fewer of these

    def on_start(self):
        self.api_key = 'rzp_test_kpJyPWio_oyI0lm0Y7_xQgeUXB3v8qfqvM5NGEGjuBn0'