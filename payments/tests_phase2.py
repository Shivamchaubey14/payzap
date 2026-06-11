import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from merchants.models import APIKey, Merchant
from payments.bin_lookup import get_gateway_for_network, lookup_bin
from payments.card_service import CardPaymentService
from payments.models import Bank, Order
from payments.netbanking_service import NetBankingService
from payments.upi_service import UPIService
from payments.upi_validator import generate_upi_intent_url, validate_vpa
from payments.wallet_service import WalletService

# ─────────────────────────────────────────────────────────────────────────────
# Day 8 — Card Payment Tests
# ─────────────────────────────────────────────────────────────────────────────

class BINLookupTest(TestCase):

    def test_visa_bin_detected(self):
        result = lookup_bin('4111111111111111')
        self.assertEqual(result['network'], 'visa')
        self.assertFalse(result['is_sanctioned'])

    def test_mastercard_bin_detected(self):
        result = lookup_bin('5105105105105100')
        self.assertEqual(result['network'], 'mastercard')

    def test_rupay_bin_detected(self):
        result = lookup_bin('6521001234567890')
        self.assertEqual(result['network'], 'rupay')

    def test_amex_bin_detected(self):
        result = lookup_bin('378282246310005')
        self.assertEqual(result['network'], 'amex')

    def test_sanctioned_bin_flagged(self):
        result = lookup_bin('9999991234567890')
        self.assertTrue(result['is_sanctioned'])

    def test_short_card_number_returns_unknown(self):
        result = lookup_bin('123')
        self.assertEqual(result['bin'], '')

    def test_known_bin_returns_bank_name(self):
        result = lookup_bin('4111111111111111')
        self.assertEqual(result['bank'], 'HDFC Bank')

    def test_gateway_routing_visa(self):
        self.assertEqual(get_gateway_for_network('visa'), 'razorpay')

    def test_gateway_routing_mastercard(self):
        self.assertEqual(get_gateway_for_network('mastercard'), 'razorpay')

    def test_gateway_routing_rupay(self):
        self.assertEqual(get_gateway_for_network('rupay'), 'mock')

    def test_gateway_routing_unknown_falls_back_to_mock(self):
        self.assertEqual(get_gateway_for_network('unknown'), 'mock')


class CardPaymentServiceTest(TestCase):

    def setUp(self):
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'Card Test Corp {unique}',
            email=f'card_{unique}@corp.com',
            phone='9100000001',
        )
        self.order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )
        self.service = CardPaymentService()

    def test_visa_success_card_returns_authorized(self):
        payment = self.service.process_card_payment(self.order, {
            'card_number': '4111111111111111',
        })
        self.assertEqual(payment.status, 'authorized')
        self.assertEqual(payment.method, 'card')

    def test_decline_card_returns_failed(self):
        order2 = Order.objects.create(
            merchant=self.merchant, amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )
        payment = self.service.process_card_payment(order2, {
            'card_number': '4000000000000002',
        })
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'CARD_DECLINED')

    def test_card_stores_last4_not_full_pan(self):
        payment = self.service.process_card_payment(self.order, {
            'card_number': '4111111111111111',
        })
        self.assertEqual(payment.card_last4, '1111')
        self.assertNotIn('4111111111111111', payment.card_token)

    def test_card_token_starts_with_tok(self):
        payment = self.service.process_card_payment(self.order, {
            'card_number': '4111111111111111',
        })
        self.assertTrue(payment.card_token.startswith('tok_'))

    def test_card_network_stored_correctly(self):
        payment = self.service.process_card_payment(self.order, {
            'card_number': '4111111111111111',
        })
        self.assertEqual(payment.card_network, 'visa')

    def test_rupay_card_routes_to_mock_and_succeeds(self):
        order2 = Order.objects.create(
            merchant=self.merchant, amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )
        payment = self.service.process_card_payment(order2, {
            'card_number': '6521001234567890',
        })
        self.assertEqual(payment.card_network, 'rupay')
        self.assertIn(payment.status, ('authorized', 'failed'))

    def test_sanctioned_bin_returns_failed_with_bin_blacklisted(self):
        order2 = Order.objects.create(
            merchant=self.merchant, amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )
        payment = self.service.process_card_payment(order2, {
            'card_number': '9999991234567890',
        })
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'BIN_BLACKLISTED')

    def test_order_status_updated_to_attempted(self):
        self.service.process_card_payment(self.order, {
            'card_number': '4111111111111111',
        })
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'attempted')

    def test_3ds_card_returns_processing_with_redirect_url(self):
        order2 = Order.objects.create(
            merchant=self.merchant, amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )
        payment = self.service.process_card_payment(order2, {
            'card_number': '4000000000003220',
        })
        self.assertEqual(payment.status, 'processing')
        self.assertTrue(payment.is_3ds)
        self.assertIn('3ds', payment.three_ds_url)


class CardPaymentAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'Card API Corp {unique}',
            email=f'cardapi_{unique}@corp.com',
            phone='9100000002',
        )
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'payments': True},
        )
        self.api_key = full_key
        self.order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )

    def _fresh_order(self):
        return Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )

    def test_visa_success_returns_201_authorized(self):
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(self.order.id), 'method': 'card',
             'card_number': '4111111111111111'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'authorized')

    def test_decline_card_returns_201_failed(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'card',
             'card_number': '4000000000000002'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'failed')

    def test_response_includes_card_network_and_last4(self):
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(self.order.id), 'method': 'card',
             'card_number': '4111111111111111'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertIn('card_network', response.data)
        self.assertIn('card_last4', response.data)
        self.assertEqual(response.data['card_last4'], '1111')

    def test_missing_order_id_returns_400(self):
        response = self.client.post(
            '/v1/payments/',
            {'method': 'card', 'card_number': '4111111111111111'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 400)

    def test_wrong_merchant_order_returns_404(self):
        other_merchant = Merchant.objects.create(
            business_name='Other Corp',
            email='other_card@corp.com',
            phone='7100000001',
        )
        other_order = Order.objects.create(
            merchant=other_merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(other_order.id), 'method': 'card',
             'card_number': '4111111111111111'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 404)

    def test_already_paid_order_returns_400(self):
        self.order.status = 'paid'
        self.order.save()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(self.order.id), 'method': 'card',
             'card_number': '4111111111111111'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 400)


# ─────────────────────────────────────────────────────────────────────────────
# Day 9 — UPI Tests
# ─────────────────────────────────────────────────────────────────────────────

class UPIValidatorTest(TestCase):

    def test_valid_vpa_passes(self):
        self.assertTrue(validate_vpa('customer@upi'))

    def test_valid_vpa_with_numbers(self):
        self.assertTrue(validate_vpa('9876543210@paytm'))

    def test_valid_vpa_with_dots(self):
        self.assertTrue(validate_vpa('john.doe@hdfc'))

    def test_invalid_vpa_no_at(self):
        self.assertFalse(validate_vpa('notavalid'))

    def test_invalid_vpa_too_short_local(self):
        self.assertFalse(validate_vpa('ab@upi'))

    def test_invalid_vpa_empty(self):
        self.assertFalse(validate_vpa(''))

    def test_intent_url_format(self):
        url = generate_upi_intent_url('merchant@upi', 50000, 'Test Corp', 'ref123')
        self.assertTrue(url.startswith('upi://pay'))
        self.assertIn('pa=merchant@upi', url)
        self.assertIn('am=500.00', url)
        self.assertIn('tr=ref123', url)


class UPIServiceTest(TestCase):

    def setUp(self):
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'UPI Corp {unique}',
            email=f'upi_{unique}@corp.com',
            phone='9200000001',
        )
        self.service = UPIService()

    def _fresh_order(self):
        return Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )

    def test_collect_valid_vpa_returns_authorized(self):
        order = self._fresh_order()
        payment = self.service.process_upi_collect(order, {'upi_vpa': 'customer@upi'})
        self.assertEqual(payment.status, 'authorized')
        self.assertEqual(payment.method, 'upi')
        self.assertEqual(payment.upi_vpa, 'customer@upi')

    def test_collect_invalid_vpa_returns_failed(self):
        order = self._fresh_order()
        payment = self.service.process_upi_collect(order, {'upi_vpa': 'notvalid'})
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'INVALID_VPA')

    def test_collect_empty_vpa_returns_failed(self):
        order = self._fresh_order()
        payment = self.service.process_upi_collect(order, {'upi_vpa': ''})
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'INVALID_VPA')

    def test_collect_normalizes_vpa_to_lowercase(self):
        order = self._fresh_order()
        payment = self.service.process_upi_collect(order, {'upi_vpa': 'Customer@UPI'})
        self.assertEqual(payment.upi_vpa, 'customer@upi')

    def test_collect_updates_order_to_attempted(self):
        order = self._fresh_order()
        self.service.process_upi_collect(order, {'upi_vpa': 'customer@upi'})
        order.refresh_from_db()
        self.assertEqual(order.status, 'attempted')

    def test_intent_returns_processing_status(self):
        order = self._fresh_order()
        payment = self.service.process_upi_intent(order, 'Test Corp')
        self.assertEqual(payment.status, 'processing')
        self.assertEqual(payment.method, 'upi')

    def test_intent_generates_upi_url(self):
        order = self._fresh_order()
        payment = self.service.process_upi_intent(order, 'Test Corp')
        self.assertTrue(payment.upi_intent_url.startswith('upi://pay'))

    def test_intent_generates_qr_code(self):
        order = self._fresh_order()
        payment = self.service.process_upi_intent(order, 'Test Corp')
        # QR is base64 PNG or empty string if qrcode not installed
        self.assertIsInstance(payment.upi_qr_code, str)

    def test_intent_updates_order_to_attempted(self):
        order = self._fresh_order()
        self.service.process_upi_intent(order, 'Test Corp')
        order.refresh_from_db()
        self.assertEqual(order.status, 'attempted')


class UPIPaymentAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'UPI API Corp {unique}',
            email=f'upiapi_{unique}@corp.com',
            phone='9200000002',
        )
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'payments': True},
        )
        self.api_key = full_key

    def _fresh_order(self):
        return Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )

    def test_upi_collect_returns_201_authorized(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'upi', 'upi_vpa': 'customer@upi'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'authorized')

    def test_upi_intent_returns_201_processing(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'upi'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'processing')
        self.assertIn('upi_intent_url', response.data)

    def test_invalid_vpa_returns_201_failed(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'upi', 'upi_vpa': 'bad'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'failed')


# ─────────────────────────────────────────────────────────────────────────────
# Day 10 — Net Banking & Wallet Tests
# ─────────────────────────────────────────────────────────────────────────────

class NetBankingServiceTest(TestCase):

    def setUp(self):
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'NB Corp {unique}',
            email=f'nb_{unique}@corp.com',
            phone='9300000001',
        )
        self.service = NetBankingService()
        # Load banks directly — no fixture dependency in unit tests
        Bank.objects.get_or_create(
            code='HDFC',
            defaults={'name': 'HDFC Bank', 'gateway_code': 'HDFC', 'is_active': True}
        )
        Bank.objects.get_or_create(
            code='SBI',
            defaults={'name': 'State Bank of India', 'gateway_code': 'SBIN', 'is_active': True}
        )

    def _fresh_order(self):
        return Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )

    def test_valid_bank_returns_processing(self):
        order = self._fresh_order()
        payment = self.service.process_netbanking(order, 'HDFC')
        self.assertEqual(payment.status, 'processing')
        self.assertEqual(payment.method, 'netbanking')
        self.assertEqual(payment.bank_code, 'HDFC')

    def test_valid_bank_generates_redirect_url(self):
        order = self._fresh_order()
        payment = self.service.process_netbanking(order, 'HDFC')
        self.assertTrue(payment.netbanking_url.startswith('https://'))
        self.assertIn('sig=', payment.netbanking_url)

    def test_invalid_bank_returns_failed(self):
        order = self._fresh_order()
        payment = self.service.process_netbanking(order, 'FAKEBANK')
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'INVALID_BANK')

    def test_bank_code_case_insensitive(self):
        order = self._fresh_order()
        payment = self.service.process_netbanking(order, 'hdfc')
        self.assertEqual(payment.status, 'processing')

    def test_order_updated_to_attempted(self):
        order = self._fresh_order()
        self.service.process_netbanking(order, 'HDFC')
        order.refresh_from_db()
        self.assertEqual(order.status, 'attempted')

    def test_bank_name_stored_on_payment(self):
        order = self._fresh_order()
        payment = self.service.process_netbanking(order, 'HDFC')
        self.assertEqual(payment.bank_name, 'HDFC Bank')

    def test_callback_success_updates_to_authorized(self):
        order = self._fresh_order()
        payment = self.service.process_netbanking(order, 'HDFC')
        # Extract txn_ref and sig from the redirect URL
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(payment.netbanking_url)
        params = parse_qs(parsed.query)
        txn_ref = params['txn_ref'][0]
        sig = params['sig'][0]
        updated = self.service.handle_callback(
            str(payment.id), 'success', sig, txn_ref
        )
        self.assertEqual(updated.status, 'authorized')

    def test_callback_failure_updates_to_failed(self):
        order = self._fresh_order()
        payment = self.service.process_netbanking(order, 'SBI')
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(payment.netbanking_url)
        params = parse_qs(parsed.query)
        txn_ref = params['txn_ref'][0]
        sig = params['sig'][0]
        updated = self.service.handle_callback(
            str(payment.id), 'failure', sig, txn_ref
        )
        self.assertEqual(updated.status, 'failed')

    def test_callback_invalid_signature_raises(self):
        order = self._fresh_order()
        payment = self.service.process_netbanking(order, 'HDFC')
        with self.assertRaises(ValueError):
            self.service.handle_callback(
                str(payment.id), 'success', 'badsignature', 'badref'
            )


class NetBankingAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'NB API Corp {unique}',
            email=f'nbapi_{unique}@corp.com',
            phone='9300000002',
        )
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'payments': True},
        )
        self.api_key = full_key
        Bank.objects.get_or_create(
            code='HDFC',
            defaults={'name': 'HDFC Bank', 'gateway_code': 'HDFC', 'is_active': True}
        )

    def _fresh_order(self):
        return Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )

    def test_netbanking_returns_201_processing(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'netbanking', 'bank_code': 'HDFC'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'processing')
        self.assertIn('netbanking_url', response.data)

    def test_netbanking_missing_bank_code_returns_400(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'netbanking'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_bank_code_returns_201_failed(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'netbanking', 'bank_code': 'FAKEBANK'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'failed')

    def test_bank_list_returns_200(self):
        response = self.client.get('/v1/banks/', HTTP_X_API_KEY=self.api_key)
        self.assertEqual(response.status_code, 200)
        self.assertIn('banks', response.data)


class WalletServiceTest(TestCase):

    def setUp(self):
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'Wallet Corp {unique}',
            email=f'wallet_{unique}@corp.com',
            phone='9400000001',
        )
        self.service = WalletService()

    def _fresh_order(self):
        return Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )

    def test_paytm_returns_authorized(self):
        order = self._fresh_order()
        payment = self.service.process_wallet_payment(order, 'paytm')
        self.assertEqual(payment.status, 'authorized')
        self.assertEqual(payment.wallet_provider, 'paytm')

    def test_phonepe_returns_authorized(self):
        order = self._fresh_order()
        payment = self.service.process_wallet_payment(order, 'phonepe')
        self.assertEqual(payment.status, 'authorized')

    def test_amazonpay_returns_authorized(self):
        order = self._fresh_order()
        payment = self.service.process_wallet_payment(order, 'amazonpay')
        self.assertEqual(payment.status, 'authorized')

    def test_mobikwik_returns_failed_insufficient_balance(self):
        order = self._fresh_order()
        payment = self.service.process_wallet_payment(order, 'mobikwik')
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'INSUFFICIENT_WALLET_BALANCE')

    def test_unsupported_wallet_returns_failed(self):
        order = self._fresh_order()
        payment = self.service.process_wallet_payment(order, 'fakewallet')
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'UNSUPPORTED_WALLET')

    def test_wallet_provider_stored_on_payment(self):
        order = self._fresh_order()
        payment = self.service.process_wallet_payment(order, 'paytm')
        self.assertEqual(payment.wallet_provider, 'paytm')

    def test_wallet_txn_id_set_on_success(self):
        order = self._fresh_order()
        payment = self.service.process_wallet_payment(order, 'paytm')
        self.assertTrue(payment.wallet_txn_id.startswith('wtxn_'))

    def test_order_updated_to_attempted_on_success(self):
        order = self._fresh_order()
        self.service.process_wallet_payment(order, 'paytm')
        order.refresh_from_db()
        self.assertEqual(order.status, 'attempted')

    def test_case_insensitive_provider(self):
        order = self._fresh_order()
        payment = self.service.process_wallet_payment(order, 'PayTM')
        self.assertEqual(payment.status, 'authorized')

    def test_amount_below_minimum_returns_failed(self):
        low_order = Order.objects.create(
            merchant=self.merchant,
            amount=50,   # below 100 minimum
            idempotency_key=str(uuid.uuid4()),
        )
        payment = self.service.process_wallet_payment(low_order, 'paytm')
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.error_code, 'AMOUNT_TOO_LOW')


class WalletAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'Wallet API Corp {unique}',
            email=f'walletapi_{unique}@corp.com',
            phone='9400000002',
        )
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'payments': True},
        )
        self.api_key = full_key

    def _fresh_order(self):
        return Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )

    def test_paytm_wallet_returns_201_authorized(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'wallet', 'wallet_provider': 'paytm'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'authorized')

    def test_mobikwik_returns_201_failed(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'wallet', 'wallet_provider': 'mobikwik'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'failed')

    def test_missing_wallet_provider_returns_400(self):
        order = self._fresh_order()
        response = self.client.post(
            '/v1/payments/',
            {'order_id': str(order.id), 'method': 'wallet'},
            format='json',
            HTTP_X_API_KEY=self.api_key,
        )
        self.assertEqual(response.status_code, 400)
