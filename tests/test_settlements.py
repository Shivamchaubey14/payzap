from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from settlements.models import Settlement
from settlements.tasks import process_daily_settlements
from tests.factories import APIKeyFactory, MerchantFactory, OrderFactory, PaymentFactory


@pytest.mark.django_db
class TestSettlementEngine:

    def setup_method(self):
        self.merchant = MerchantFactory(
            is_live=True,
            kyc_status='approved',
            fee_rate=0.02,
            bank_account_number='1234567890',
            bank_ifsc='HDFC0001234',
        )

    def test_settlement_creates_record_for_captured_payments(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        PaymentFactory(
            order=order,
            amount=100000,
            status='captured',
            in_settlement=False,
        )

        with patch('webhooks.tasks.dispatch_webhook_event.delay'):
            process_daily_settlements()

        settlement = Settlement.objects.filter(merchant=self.merchant).first()
        assert settlement is not None
        assert settlement.status == 'processed'
        assert settlement.utr_number.startswith('UTR')

    def test_settlement_amount_deducts_fee(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        PaymentFactory(
            order=order,
            amount=100000,
            status='captured',
            in_settlement=False,
        )

        with patch('webhooks.tasks.dispatch_webhook_event.delay'):
            process_daily_settlements()

        settlement = Settlement.objects.filter(merchant=self.merchant).first()
        # 2% fee on 100000 = 2000, payout = 98000
        assert settlement.fees == 2000
        assert settlement.amount == 98000

    def test_settlement_deducts_refunds(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        PaymentFactory(
            order=order,
            amount=100000,
            amount_refunded=40000,
            status='captured',
            in_settlement=False,
        )

        with patch('webhooks.tasks.dispatch_webhook_event.delay'):
            process_daily_settlements()

        settlement = Settlement.objects.filter(merchant=self.merchant).first()
        # net = 100000 - 40000 = 60000, fee 2% = 1200, payout = 58800
        assert settlement.amount == 58800

    def test_no_settlement_for_zero_captured(self):
        # No payments at all
        with patch('webhooks.tasks.dispatch_webhook_event.delay'):
            process_daily_settlements()

        assert Settlement.objects.filter(merchant=self.merchant).count() == 0

    def test_no_settlement_for_inactive_merchant(self):
        inactive = MerchantFactory(is_live=False, kyc_status='approved')
        order = OrderFactory(merchant=inactive, amount=100000)
        PaymentFactory(order=order, amount=100000, status='captured', in_settlement=False)

        with patch('webhooks.tasks.dispatch_webhook_event.delay'):
            process_daily_settlements()

        assert Settlement.objects.filter(merchant=inactive).count() == 0

    def test_payments_marked_in_settlement_after_processing(self):
        order = OrderFactory(merchant=self.merchant, amount=100000)
        payment = PaymentFactory(
            order=order,
            amount=100000,
            status='captured',
            in_settlement=False,
        )

        with patch('webhooks.tasks.dispatch_webhook_event.delay'):
            process_daily_settlements()

        payment.refresh_from_db()
        assert payment.in_settlement is True


@pytest.mark.django_db
class TestSettlementAPI:

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory(is_live=True, kyc_status='approved')
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_list_settlements_empty(self):
        resp = self.client.get('/v1/settlements/')
        assert resp.status_code == 200
        assert resp.data['count'] == 0

    def test_list_settlements_returns_merchant_own_only(self):
        other_merchant = MerchantFactory(is_live=True, kyc_status='approved')
        Settlement.objects.create(
            merchant=self.merchant,
            amount=98000,
            fees=2000,
            status='processed',
            settlement_from=timezone.now(),
            settlement_to=timezone.now(),
        )
        Settlement.objects.create(
            merchant=other_merchant,
            amount=49000,
            fees=1000,
            status='processed',
            settlement_from=timezone.now(),
            settlement_to=timezone.now(),
        )

        resp = self.client.get('/v1/settlements/')
        assert resp.status_code == 200
        assert resp.data['count'] == 1
        assert resp.data['items'][0]['amount'] == 98000
