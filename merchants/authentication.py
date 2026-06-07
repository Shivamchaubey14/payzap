import hashlib
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from merchants.models import APIKey, Merchant


class APIKeyAuthentication(BaseAuthentication):
    """
    Custom DRF authentication using PayZap API keys.
    Merchants send: Authorization: Basic <base64(api_key:)>
    Or directly:    X-Api-Key: rzp_live_xxxxx
    """

    def authenticate(self, request):
        # Support both X-Api-Key header and HTTP Basic Auth
        api_key = self._extract_key(request)
        if not api_key:
            return None  # Let other authenticators try

        return self._validate_key(api_key)

    def _extract_key(self, request):
        # Try X-Api-Key header first
        key = request.META.get('HTTP_X_API_KEY')
        if key:
            return key

        # Try HTTP Basic Auth (key as username, empty password)
        import base64
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Basic '):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
                key = decoded.split(':')[0]
                if key.startswith(('rzp_live_', 'rzp_test_')):
                    return key
            except Exception:
                pass

        return None

    def _validate_key(self, api_key):
        # Extract prefix (first 20 chars: "rzp_live_XXXXXXXX")
        parts = api_key.split('_')
        if len(parts) < 3:
            raise AuthenticationFailed('Invalid API key format.')

        prefix = f"{parts[0]}_{parts[1]}_{parts[2]}"

        # Look up by prefix
        try:
            key_obj = APIKey.objects.select_related('merchant').get(
                key_prefix=prefix,
                is_active=True,
            )
        except APIKey.DoesNotExist:
            raise AuthenticationFailed('Invalid API key.')

        # Verify hash
        key_hash = hashlib.pbkdf2_hmac(
            'sha256', api_key.encode(), b'payzap_salt', 100000
        ).hex()

        if key_hash != key_obj.key_hash:
            raise AuthenticationFailed('Invalid API key.')

        # Check merchant is active
        if not key_obj.merchant.is_active:
            raise AuthenticationFailed('Merchant account is suspended.')

        # Update last used timestamp (non-blocking)
        APIKey.objects.filter(pk=key_obj.pk).update(last_used_at=timezone.now())

        return (key_obj.merchant, key_obj)

    def authenticate_header(self, request):
        return 'Basic realm="PayZap API"'