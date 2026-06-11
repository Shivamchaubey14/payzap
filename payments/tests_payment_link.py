import uuid
from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from merchants.models import APIKey, Merchant
from payments.models import Order, Payment, PaymentLink, VirtualAccount
from payments.payment_link_service import PaymentLinkService
from payments.virtual_account_service import VirtualAccountService

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_merchant(prefix='day23'):
    unique = uuid.uuid4().hex[:8]
    return Merchant.objects.create(
        business_name=f'{prefix} Corp {unique}',
        email=f'{prefix}_{unique}@corp.com',
        phone='9600000001',
    )


def make_api_client(merchant):
    full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
    APIKey.objects.create(
        merchant=merchant,
        key_prefix=prefix,
        key_hash=key_hash,
        is_live=False,
        permissions={'payments': True},
    )
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=full_key)
    return client, full_key


# ─────────────────────────────────────────────────────────────────────────────
# PaymentLink Model Tests
# ─────────────────────────────────────────────────────────────────────────────

class PaymentLinkModelTest(TestCase):

    def setUp(self):
        self.merchant = make_merchant('link_model')

    def test_payment_link_created_with_uuid(self):
        link = PaymentLink.objects.create(
            merchant=self.merchant,
            slug=PaymentLink.generate_slug(),
            amount=50000,
            currency='INR',
        )
        self.assertIsNotNone(link.id)

    def test_default_status_is_active(self):
        link = PaymentLink.objects.create(
            merchant=self.merchant,
            slug=PaymentLink.generate_slug(),
            amount=50000,
        )
        self.assertEqual(link.status, 'active')

    def test_amount_in_rupees_property(self):
        link = PaymentLink.objects.create(
            merchant=self.merchant,
            slug=PaymentLink.generate_slug(),
            amount=75000,
        )
        self.assertEqual(link.amount_in_rupees, 750.0)

    def test_open_amount_link_amount_in_rupees_is_none(self):
        link = PaymentLink.objects.create(
            merchant=self.merchant,
            slug=PaymentLink.generate_slug(),
            amount=None,
        )
        self.assertIsNone(link.amount_in_rupees)

    def test_is_usable_active_link(self):
        link = PaymentLink.objects.create(
            merchant=self.merchant,
            slug=PaymentLink.generate_slug(),
            amount=50000,
            status='active',
        )
        self.assertTrue(link.is_usable)

    def test_is_usable_disabled_link(self):
        link = PaymentLink.objects.create(
            merchant=self.merchant,
            slug=PaymentLink.generate_slug(),
            amount=50000,
            status='disabled',
        )
        self.assertFalse(link.is_usable)

    def test_is_usable_expired_link(self):
        link = PaymentLink.objects.create(
            merchant=self.merchant,
            slug=PaymentLink.generate_slug(),
            amount=50000,
            status='active',
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(link.is_usable)

    def test_is_usable_max_uses_reached(self):
        link = PaymentLink.objects.create(
            merchant=self.merchant,
            slug=PaymentLink.generate_slug(),
            amount=50000,
            status='active',
            max_uses=2,
            use_count=2,
        )
        self.assertFalse(link.is_usable)

    def test_generate_slug_is_unique(self):
        slug1 = PaymentLink.generate_slug()
        slug2 = PaymentLink.generate_slug()
        self.assertNotEqual(slug1, slug2)

    def test_slug_is_unique_in_db(self):
        slug = PaymentLink.generate_slug()
        PaymentLink.objects.create(
            merchant=self.merchant, slug=slug, amount=50000
        )
        with self.assertRaises(IntegrityError):
            PaymentLink.objects.create(
                merchant=self.merchant, slug=slug, amount=50000
            )


# ─────────────────────────────────────────────────────────────────────────────
# PaymentLinkService Tests
# ─────────────────────────────────────────────────────────────────────────────

class PaymentLinkServiceTest(TestCase):

    def setUp(self):
        self.merchant = make_merchant('link_service')
        self.service = PaymentLinkService()

    def test_create_link_returns_payment_link(self):
        link = self.service.create_link(self.merchant, {'amount': 50000})
        self.assertIsInstance(link, PaymentLink)

    def test_create_link_slug_is_set(self):
        link = self.service.create_link(self.merchant, {'amount': 50000})
        self.assertTrue(len(link.slug) > 0)

    def test_create_link_with_max_uses(self):
        link = self.service.create_link(self.merchant, {'amount': 50000, 'max_uses': 5})
        self.assertEqual(link.max_uses, 5)

    def test_create_open_amount_link(self):
        link = self.service.create_link(self.merchant, {})
        self.assertIsNone(link.amount)

    def test_create_link_with_expiry(self):
        expiry = timezone.now() + timedelta(days=7)
        link = self.service.create_link(self.merchant, {
            'amount': 50000, 'expires_at': expiry
        })
        self.assertIsNotNone(link.expires_at)

    def test_get_link_by_slug(self):
        link = self.service.create_link(self.merchant, {'amount': 50000})
        fetched = self.service.get_link(link.slug)
        self.assertEqual(fetched.id, link.id)

    def test_get_nonexistent_slug_raises(self):
        with self.assertRaises(ValueError):
            self.service.get_link('nonexistent-slug-xyz')

    def test_record_payment_creates_order(self):
        link = self.service.create_link(self.merchant, {'amount': 50000})
        order = self.service.record_payment(link, amount=50000)
        self.assertIsInstance(order, Order)
        self.assertEqual(order.amount, 50000)

    def test_record_payment_increments_use_count(self):
        link = self.service.create_link(self.merchant, {'amount': 50000})
        self.service.record_payment(link, amount=50000)
        link.refresh_from_db()
        self.assertEqual(link.use_count, 1)

    def test_record_payment_auto_closes_at_max_uses(self):
        link = self.service.create_link(self.merchant, {
            'amount': 50000, 'max_uses': 1
        })
        self.service.record_payment(link, amount=50000)
        link.refresh_from_db()
        self.assertEqual(link.status, 'paid')

    def test_record_payment_on_disabled_link_raises(self):
        link = self.service.create_link(self.merchant, {'amount': 50000})
        PaymentLink.objects.filter(id=link.id).update(status='disabled')
        link.refresh_from_db()
        with self.assertRaises(ValueError):
            self.service.record_payment(link, amount=50000)

    def test_record_payment_on_expired_link_raises(self):
        link = self.service.create_link(self.merchant, {
            'amount': 50000,
            'expires_at': timezone.now() - timedelta(hours=1),
        })
        with self.assertRaises(ValueError):
            self.service.record_payment(link, amount=50000)

    def test_open_amount_link_uses_provided_amount(self):
        link = self.service.create_link(self.merchant, {})
        order = self.service.record_payment(link, amount=30000)
        self.assertEqual(order.amount, 30000)

    def test_open_amount_link_zero_amount_raises(self):
        link = self.service.create_link(self.merchant, {})
        with self.assertRaises(ValueError):
            self.service.record_payment(link, amount=0)

    def test_disable_link(self):
        link = self.service.create_link(self.merchant, {'amount': 50000})
        self.service.disable_link(link, self.merchant)
        link.refresh_from_db()
        self.assertEqual(link.status, 'disabled')

    def test_disable_link_wrong_merchant_raises(self):
        link = self.service.create_link(self.merchant, {'amount': 50000})
        other = make_merchant('other_link')
        with self.assertRaises(ValueError):
            self.service.disable_link(link, other)


# ─────────────────────────────────────────────────────────────────────────────
# PaymentLink API Tests
# ─────────────────────────────────────────────────────────────────────────────

class PaymentLinkAPITest(TestCase):

    def setUp(self):
        self.merchant = make_merchant('link_api')
        self.client, self.api_key = make_api_client(self.merchant)

    def test_create_link_returns_201(self):
        response = self.client.post(
            '/v1/payment_links/create/',
            {'amount': 50000, 'currency': 'INR', 'description': 'Test'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_create_link_response_has_slug(self):
        response = self.client.post(
            '/v1/payment_links/create/',
            {'amount': 50000},
            format='json',
        )
        self.assertIn('slug', response.data)
        self.assertTrue(len(response.data['slug']) > 0)

    def test_create_link_response_has_checkout_url(self):
        response = self.client.post(
            '/v1/payment_links/create/',
            {'amount': 50000},
            format='json',
        )
        self.assertIn('checkout_url', response.data)
        self.assertIn('/pay/', response.data['checkout_url'])

    def test_create_link_amount_in_rupees_correct(self):
        response = self.client.post(
            '/v1/payment_links/create/',
            {'amount': 50000},
            format='json',
        )
        self.assertEqual(response.data['amount_in_rupees'], 500.0)

    def test_create_open_amount_link(self):
        response = self.client.post(
            '/v1/payment_links/create/',
            {'description': 'Open amount link'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['amount'])

    def test_list_links_returns_200(self):
        self.client.post('/v1/payment_links/create/', {'amount': 10000}, format='json')
        self.client.post('/v1/payment_links/create/', {'amount': 20000}, format='json')
        response = self.client.get('/v1/payment_links/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)

    def test_get_link_detail_returns_200(self):
        create = self.client.post(
            '/v1/payment_links/create/', {'amount': 50000}, format='json'
        )
        link_id = create.data['id']
        response = self.client.get(f'/v1/payment_links/{link_id}/')
        self.assertEqual(response.status_code, 200)

    def test_get_other_merchant_link_returns_404(self):
        other = make_merchant('other_link_api')
        other_client, _ = make_api_client(other)
        create = other_client.post(
            '/v1/payment_links/create/', {'amount': 50000}, format='json'
        )
        link_id = create.data['id']
        response = self.client.get(f'/v1/payment_links/{link_id}/')
        self.assertEqual(response.status_code, 404)

    def test_disable_link_returns_disabled(self):
        create = self.client.post(
            '/v1/payment_links/create/', {'amount': 50000}, format='json'
        )
        link_id = create.data['id']
        response = self.client.delete(f'/v1/payment_links/{link_id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'disabled')

    def test_checkout_page_returns_200_for_active_link(self):
        create = self.client.post(
            '/v1/payment_links/create/', {'amount': 50000}, format='json'
        )
        slug = create.data['slug']
        bare = APIClient()
        response = bare.get(f'/pay/{slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('slug', response.data)

    def test_checkout_page_returns_404_for_bad_slug(self):
        bare = APIClient()
        response = bare.get('/pay/nonexistent-slug-xyz/')
        self.assertEqual(response.status_code, 404)

    def test_checkout_page_returns_410_for_disabled_link(self):
        create = self.client.post(
            '/v1/payment_links/create/', {'amount': 50000}, format='json'
        )
        link_id = create.data['id']
        slug = create.data['slug']
        self.client.delete(f'/v1/payment_links/{link_id}/')
        bare = APIClient()
        response = bare.get(f'/pay/{slug}/')
        self.assertEqual(response.status_code, 410)

    def test_unauthenticated_create_returns_401(self):
        bare = APIClient()
        response = bare.post(
            '/v1/payment_links/create/', {'amount': 50000}, format='json'
        )
        self.assertEqual(response.status_code, 401)


# ─────────────────────────────────────────────────────────────────────────────
# VirtualAccount Model Tests
# ─────────────────────────────────────────────────────────────────────────────

class VirtualAccountModelTest(TestCase):

    def setUp(self):
        self.merchant = make_merchant('va_model')

    def test_virtual_account_created_with_uuid(self):
        va = VirtualAccount.objects.create(
            merchant=self.merchant,
            name='Test VA',
            virtual_upi_id='payzap.va.test001@payzap',
            virtual_account_number='PAYZTEST001',
        )
        self.assertIsNotNone(va.id)

    def test_default_status_is_active(self):
        va = VirtualAccount.objects.create(
            merchant=self.merchant,
            name='Test VA',
            virtual_upi_id='payzap.va.test002@payzap',
            virtual_account_number='PAYZTEST002',
        )
        self.assertEqual(va.status, 'active')

    def test_amount_paid_defaults_to_zero(self):
        va = VirtualAccount.objects.create(
            merchant=self.merchant,
            name='Test VA',
            virtual_upi_id='payzap.va.test003@payzap',
            virtual_account_number='PAYZTEST003',
        )
        self.assertEqual(va.amount_paid, 0)

    def test_virtual_upi_id_is_unique(self):
        VirtualAccount.objects.create(
            merchant=self.merchant,
            name='VA 1',
            virtual_upi_id='payzap.va.dup@payzap',
            virtual_account_number='PAYZDUP001',
        )
        with self.assertRaises(IntegrityError):
            VirtualAccount.objects.create(
                merchant=self.merchant,
                name='VA 2',
                virtual_upi_id='payzap.va.dup@payzap',
                virtual_account_number='PAYZDUP002',
            )


# ─────────────────────────────────────────────────────────────────────────────
# VirtualAccountService Tests
# ─────────────────────────────────────────────────────────────────────────────

class VirtualAccountServiceTest(TestCase):

    def setUp(self):
        self.merchant = make_merchant('va_service')
        self.service = VirtualAccountService()

    def test_create_virtual_account_returns_va(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Client A'}
        )
        self.assertIsInstance(va, VirtualAccount)

    def test_virtual_upi_id_format(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Client B'}
        )
        self.assertTrue(va.virtual_upi_id.startswith('payzap.va.'))
        self.assertTrue(va.virtual_upi_id.endswith('@payzap'))

    def test_virtual_account_number_format(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Client C'}
        )
        self.assertTrue(va.virtual_account_number.startswith('PAYZ'))

    def test_two_vas_have_different_upi_ids(self):
        va1 = self.service.create_virtual_account(self.merchant, {'name': 'A'})
        va2 = self.service.create_virtual_account(self.merchant, {'name': 'B'})
        self.assertNotEqual(va1.virtual_upi_id, va2.virtual_upi_id)

    def test_create_with_amount_expected(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Invoice', 'amount_expected': 100000}
        )
        self.assertEqual(va.amount_expected, 100000)

    def test_record_credit_creates_payment(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Collector'}
        )
        payment = self.service.record_credit(va, amount=50000)
        self.assertIsInstance(payment, Payment)
        self.assertEqual(payment.status, 'captured')

    def test_record_credit_creates_order(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Collector'}
        )
        payment = self.service.record_credit(va, amount=50000)
        self.assertIsNotNone(payment.order)
        self.assertEqual(payment.order.amount, 50000)

    def test_record_credit_updates_amount_paid(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Collector'}
        )
        self.service.record_credit(va, amount=50000)
        va.refresh_from_db()
        self.assertEqual(va.amount_paid, 50000)

    def test_two_credits_accumulate_amount_paid(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Collector'}
        )
        self.service.record_credit(va, amount=40000)
        va.refresh_from_db()
        self.service.record_credit(va, amount=60000)
        va.refresh_from_db()
        self.assertEqual(va.amount_paid, 100000)

    def test_va_auto_closes_when_amount_expected_met(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Invoice', 'amount_expected': 50000}
        )
        self.service.record_credit(va, amount=50000)
        va.refresh_from_db()
        self.assertEqual(va.status, 'closed')

    def test_va_stays_active_if_partially_paid(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Invoice', 'amount_expected': 100000}
        )
        self.service.record_credit(va, amount=50000)
        va.refresh_from_db()
        self.assertEqual(va.status, 'active')

    def test_record_credit_on_closed_va_raises(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Invoice', 'amount_expected': 50000}
        )
        self.service.record_credit(va, amount=50000)
        va.refresh_from_db()
        with self.assertRaises(ValueError):
            self.service.record_credit(va, amount=10000)

    def test_close_account(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Invoice'}
        )
        self.service.close_account(va, self.merchant)
        va.refresh_from_db()
        self.assertEqual(va.status, 'closed')

    def test_close_account_wrong_merchant_raises(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'Invoice'}
        )
        other = make_merchant('other_va')
        with self.assertRaises(ValueError):
            self.service.close_account(va, other)

    def test_payment_method_stored_correctly(self):
        va = self.service.create_virtual_account(
            self.merchant, {'name': 'NEFT Collector'}
        )
        payment = self.service.record_credit(va, amount=50000, payment_method='netbanking')
        self.assertEqual(payment.method, 'netbanking')


# ─────────────────────────────────────────────────────────────────────────────
# VirtualAccount API Tests
# ─────────────────────────────────────────────────────────────────────────────

class VirtualAccountAPITest(TestCase):

    def setUp(self):
        self.merchant = make_merchant('va_api')
        self.client, self.api_key = make_api_client(self.merchant)

    def test_create_va_returns_201(self):
        response = self.client.post(
            '/v1/virtual_accounts/',
            {'name': 'Client Collections', 'amount_expected': 100000},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_create_va_response_has_upi_id(self):
        response = self.client.post(
            '/v1/virtual_accounts/',
            {'name': 'Client Collections'},
            format='json',
        )
        self.assertIn('virtual_upi_id', response.data)
        self.assertTrue(response.data['virtual_upi_id'].startswith('payzap.va.'))

    def test_create_va_response_has_account_number(self):
        response = self.client.post(
            '/v1/virtual_accounts/',
            {'name': 'Client Collections'},
            format='json',
        )
        self.assertIn('virtual_account_number', response.data)

    def test_get_va_detail_returns_200(self):
        create = self.client.post(
            '/v1/virtual_accounts/',
            {'name': 'Test VA'},
            format='json',
        )
        va_id = create.data['id']
        response = self.client.get(f'/v1/virtual_accounts/{va_id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data['id']), str(va_id))

    def test_get_nonexistent_va_returns_404(self):
        response = self.client.get(f'/v1/virtual_accounts/{uuid.uuid4()}/')
        self.assertEqual(response.status_code, 404)

    def test_get_other_merchant_va_returns_404(self):
        other = make_merchant('other_va_api')
        other_client, _ = make_api_client(other)
        create = other_client.post(
            '/v1/virtual_accounts/', {'name': 'Other VA'}, format='json'
        )
        va_id = create.data['id']
        response = self.client.get(f'/v1/virtual_accounts/{va_id}/')
        self.assertEqual(response.status_code, 404)

    def test_credit_va_returns_201(self):
        create = self.client.post(
            '/v1/virtual_accounts/', {'name': 'Test VA'}, format='json'
        )
        va_id = create.data['id']
        response = self.client.post(
            f'/v1/virtual_accounts/{va_id}/credit/',
            {'amount': 50000, 'method': 'upi'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_credit_response_status_is_captured(self):
        create = self.client.post(
            '/v1/virtual_accounts/', {'name': 'Test VA'}, format='json'
        )
        va_id = create.data['id']
        response = self.client.post(
            f'/v1/virtual_accounts/{va_id}/credit/',
            {'amount': 50000, 'method': 'upi'},
            format='json',
        )
        self.assertEqual(response.data['status'], 'captured')

    def test_credit_missing_amount_returns_400(self):
        create = self.client.post(
            '/v1/virtual_accounts/', {'name': 'Test VA'}, format='json'
        )
        va_id = create.data['id']
        response = self.client.post(
            f'/v1/virtual_accounts/{va_id}/credit/',
            {'method': 'upi'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_close_va_returns_closed_status(self):
        create = self.client.post(
            '/v1/virtual_accounts/', {'name': 'Test VA'}, format='json'
        )
        va_id = create.data['id']
        response = self.client.delete(f'/v1/virtual_accounts/{va_id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'closed')

    def test_credit_closed_va_returns_400(self):
        create = self.client.post(
            '/v1/virtual_accounts/', {'name': 'Test VA'}, format='json'
        )
        va_id = create.data['id']
        self.client.delete(f'/v1/virtual_accounts/{va_id}/')
        response = self.client.post(
            f'/v1/virtual_accounts/{va_id}/credit/',
            {'amount': 50000},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_unauthenticated_create_returns_401(self):
        bare = APIClient()
        response = bare.post(
            '/v1/virtual_accounts/', {'name': 'Test'}, format='json'
        )
        self.assertEqual(response.status_code, 401)
