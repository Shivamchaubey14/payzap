import base64
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
        # Prefix is always "rzp_live_XXXXXXXX" or "rzp_test_XXXXXXXX"
        # Format: {mode}_{8-char-segment}_{rest}
        # We can't split by '_' because token_urlsafe output can contain '_'
        # Instead, extract prefix as everything before the 3rd underscore-delimited segment
        # Structure: rzp _ test _ <8chars> _ <rest>
        #            [0]   [1]     [2]       [3+]
        # But raw[:8] may itself contain '_', so we CANNOT rely on split('_')
        # The prefix was stored as f"rzp_{'live' if live else 'test'}_{raw[:8]}"
        # and full_key = f"{prefix}_{raw[8:]}"
        # So: prefix = full_key up to the (9 + len('rzp_test_')) char boundary

        if api_key.startswith('rzp_live_'):
            mode_prefix = 'rzp_live_'
        elif api_key.startswith('rzp_test_'):
            mode_prefix = 'rzp_test_'
        else:
            raise AuthenticationFailed('Invalid API key format.')

        # prefix = "rzp_test_" + next 8 characters
        if len(api_key) < len(mode_prefix) + 8:
            raise AuthenticationFailed('Invalid API key format.')

        prefix = api_key[:len(mode_prefix) + 8]  # e.g. "rzp_test_qw_Bh7uM"

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