import pytest
from django.test import TestCase
from merchants.models import Merchant, APIKey


class MerchantModelTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name="Test Corp",
            email="test@testcorp.com",
            phone="9999999999",
            pan="ABCDE1234F",
            gstin="22ABCDE1234F1Z5",
        )

    def test_merchant_created_with_uuid(self):
        self.assertIsNotNone(self.merchant.id)
        self.assertEqual(str(self.merchant.id), str(self.merchant.pk))

    def test_default_kyc_status_is_pending(self):
        self.assertEqual(self.merchant.kyc_status, 'pending')

    def test_default_fee_rate(self):
        self.assertEqual(float(self.merchant.fee_rate), 0.02)

    def test_merchant_is_not_live_by_default(self):
        self.assertFalse(self.merchant.is_live)

    def test_merchant_str(self):
        self.assertIn("Test Corp", str(self.merchant))

    def test_merchant_is_active_by_default(self):
        self.assertTrue(self.merchant.is_active)


class APIKeyModelTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name="Key Corp",
            email="key@keycorp.com",
            phone="8888888888",
        )

    def test_generate_test_key(self):
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        self.assertTrue(prefix.startswith('rzp_test_'))
        self.assertIn(prefix, full_key)
        self.assertEqual(len(key_hash), 64)  # SHA256 hex = 64 chars

    def test_generate_live_key(self):
        full_key, prefix, key_hash = APIKey.generate_key(is_live=True)
        self.assertTrue(prefix.startswith('rzp_live_'))

    def test_api_key_hash_is_not_raw_key(self):
        full_key, prefix, key_hash = APIKey.generate_key()
        self.assertNotEqual(full_key, key_hash)

    def test_create_api_key(self):
        full_key, prefix, key_hash = APIKey.generate_key()
        api_key = APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={"payments": True, "refunds": True},
        )
        self.assertEqual(api_key.merchant, self.merchant)
        self.assertFalse(api_key.is_live)
        self.assertTrue(api_key.is_active)
        self.assertIsNone(api_key.last_used_at)

    def test_api_key_str(self):
        full_key, prefix, key_hash = APIKey.generate_key()
        api_key = APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
        )
        self.assertIn('test', str(api_key))