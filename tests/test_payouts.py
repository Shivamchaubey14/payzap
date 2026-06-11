from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from payouts.models import Payout
from tests.factories import APIKeyFactory, MerchantFactory


@pytest.mark.django_db
class TestPayoutCreate:

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory()
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_create_imps_payout_success(self):
        with patch('payouts.tasks.process_payout_task.delay'):
            resp = self.client.post('/v1/payouts/create/', {
                'amount': 50000,
                'mode': 'IMPS',
                'purpose': 'vendor',
                'beneficiary_name': 'John Doe',
                'account_number': '123456789012',
                'ifsc': 'HDFC0001234',
            }, format='json')
        assert resp.status_code == 201
        assert resp.data['status'] == 'queued'
        assert resp.data['amount'] == 50000

    def test_create_upi_payout_success(self):
        with patch('payouts.tasks.process_payout_task.delay'):
            resp = self.client.post('/v1/payouts/create/', {
                'amount': 10000,
                'mode': 'UPI',
                'purpose': 'payout',
                'beneficiary_name': 'Jane Doe',
                'upi_id': 'jane@upi',
            }, format='json')
        assert resp.status_code == 201
        assert resp.data['mode'] == 'UPI'

    def test_missing_ifsc_returns_400(self):
        resp = self.client.post('/v1/payouts/create/', {
            'amount': 50000,
            'mode': 'IMPS',
            'beneficiary_name': 'John Doe',
            'account_number': '123456789012',
        }, format='json')
        assert resp.status_code == 400

    def test_invalid_ifsc_format_returns_400(self):
        resp = self.client.post('/v1/payouts/create/', {
            'amount': 50000,
            'mode': 'IMPS',
            'beneficiary_name': 'John Doe',
            'account_number': '123456789012',
            'ifsc': 'INVALID',
        }, format='json')
        assert resp.status_code == 400

    def test_invalid_upi_id_returns_400(self):
        resp = self.client.post('/v1/payouts/create/', {
            'amount': 10000,
            'mode': 'UPI',
            'beneficiary_name': 'Jane',
            'upi_id': 'not-a-valid-upi',
        }, format='json')
        assert resp.status_code == 400

    def test_zero_amount_returns_400(self):
        resp = self.client.post('/v1/payouts/create/', {
            'amount': 0,
            'mode': 'IMPS',
            'beneficiary_name': 'John',
            'account_number': '123456789012',
            'ifsc': 'HDFC0001234',
        }, format='json')
        assert resp.status_code == 400

    def test_daily_limit_exceeded_returns_400(self):
        # Create payouts totalling the daily limit
        Payout.objects.create(
            merchant=self.merchant,
            amount=10_000_000,
            mode='IMPS',
            beneficiary_name='Someone',
            account_number='123456789',
            ifsc='HDFC0001234',
            status='queued',
        )
        resp = self.client.post('/v1/payouts/create/', {
            'amount': 1,
            'mode': 'IMPS',
            'beneficiary_name': 'John',
            'account_number': '123456789012',
            'ifsc': 'HDFC0001234',
        }, format='json')
        assert resp.status_code == 400
        assert 'limit' in resp.data['error'].lower()


@pytest.mark.django_db
class TestPayoutProcess:

    def setup_method(self):
        self.merchant = MerchantFactory()

    def test_process_payout_sets_processed_status(self):
        payout = Payout.objects.create(
            merchant=self.merchant,
            amount=50000,
            mode='IMPS',
            beneficiary_name='Test',
            account_number='123456789012',
            ifsc='HDFC0001234',
            status='queued',
        )
        with patch('webhooks.tasks.dispatch_webhook_event.delay'):
            from payouts.payout_service import process_payout
            process_payout(str(payout.id))

        payout.refresh_from_db()
        assert payout.status == 'processed'
        assert payout.utr_number.startswith('UTR')
        assert payout.processed_at is not None

    def test_process_payout_fires_webhook(self):
        payout = Payout.objects.create(
            merchant=self.merchant,
            amount=50000,
            mode='IMPS',
            beneficiary_name='Test',
            account_number='123456789012',
            ifsc='HDFC0001234',
            status='queued',
        )
        with patch('webhooks.tasks.dispatch_webhook_event.delay') as mock_webhook:
            from payouts.payout_service import process_payout
            process_payout(str(payout.id))

        mock_webhook.assert_called_once()
        call_args = mock_webhook.call_args[0]
        assert call_args[1] == 'payout.processed'


@pytest.mark.django_db
class TestPayoutList:

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory()
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_list_payouts_empty(self):
        resp = self.client.get('/v1/payouts/')
        assert resp.status_code == 200
        assert resp.data['count'] == 0

    def test_list_payouts_merchant_isolation(self):
        other_merchant = MerchantFactory()
        Payout.objects.create(
            merchant=other_merchant,
            amount=50000,
            mode='IMPS',
            beneficiary_name='Other',
            account_number='123456789012',
            ifsc='HDFC0001234',
            status='processed',
        )
        resp = self.client.get('/v1/payouts/')
        assert resp.data['count'] == 0

    def test_get_payout_detail(self):
        payout = Payout.objects.create(
            merchant=self.merchant,
            amount=50000,
            mode='IMPS',
            beneficiary_name='Test',
            account_number='123456789012',
            ifsc='HDFC0001234',
            status='processed',
        )
        resp = self.client.get(f'/v1/payouts/{payout.id}/')
        assert resp.status_code == 200
        assert str(resp.data['id']) == str(payout.id)
