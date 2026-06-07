from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from merchants.models import Merchant, APIKey


class RegistrationViewTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = '/v1/accounts/register/'
        self.valid_payload = {
            'business_name': 'Auth Test Corp',
            'email': 'authtest@corp.com',
            'phone': '9876543210',
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123',
        }

    def test_registration_returns_201(self):
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, 201)

    def test_registration_returns_merchant_id_and_api_key(self):
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertIn('merchant_id', response.data)
        self.assertIn('test_api_key', response.data)
        self.assertTrue(response.data['test_api_key'].startswith('rzp_test_'))

    def test_registration_creates_merchant_in_db(self):
        self.client.post(self.url, self.valid_payload, format='json')
        self.assertTrue(Merchant.objects.filter(email='authtest@corp.com').exists())

    def test_registration_creates_django_user(self):
        self.client.post(self.url, self.valid_payload, format='json')
        self.assertTrue(User.objects.filter(email='authtest@corp.com').exists())

    def test_registration_user_inactive_until_verified(self):
        self.client.post(self.url, self.valid_payload, format='json')
        user = User.objects.get(email='authtest@corp.com')
        self.assertFalse(user.is_active)

    def test_duplicate_email_returns_400(self):
        self.client.post(self.url, self.valid_payload, format='json')
        response = self.client.post(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_password_mismatch_returns_400(self):
        payload = {**self.valid_payload, 'confirm_password': 'WrongPass123'}
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_missing_email_returns_400(self):
        payload = {**self.valid_payload}
        del payload['email']
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_api_key_hash_not_stored_as_plaintext(self):
        response = self.client.post(self.url, self.valid_payload, format='json')
        full_key = response.data['test_api_key']
        api_key_obj = APIKey.objects.first()
        self.assertNotEqual(api_key_obj.key_hash, full_key)


class APIKeyAuthenticationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        # Register a merchant and grab their API key
        response = self.client.post('/v1/accounts/register/', {
            'business_name': 'API Auth Corp',
            'email': 'apiauth@corp.com',
            'phone': '9000000000',
            'password': 'SecurePass123',
            'confirm_password': 'SecurePass123',
        }, format='json')
        self.api_key = response.data['test_api_key']

    def test_profile_with_valid_api_key(self):
        response = self.client.get(
            '/v1/accounts/me/',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['email'], 'apiauth@corp.com')

    def test_profile_with_invalid_api_key_returns_401(self):
        response = self.client.get(
            '/v1/accounts/me/',
            HTTP_X_API_KEY='rzp_test_FAKEKEYxxxxx'
        )
        self.assertEqual(response.status_code, 401)

    def test_profile_without_api_key_returns_401(self):
        response = self.client.get('/v1/accounts/me/')
        self.assertEqual(response.status_code, 401)