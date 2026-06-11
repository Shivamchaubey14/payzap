import json

from django.core.cache import cache
from django.http import JsonResponse


class IdempotencyMiddleware:
    """
    Checks Redis for a cached response before processing any POST to /v1/.
    If found, returns the cached response immediately — zero double processing.
    Key format: idempotency:{merchant_key_prefix}:{idempotency_key}
    TTL: 24 hours
    """
    CACHE_TTL = 86400  # 24 hours in seconds

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only apply to POST requests on API endpoints
        if request.method != 'POST' or not request.path.startswith('/v1/'):
            return self.get_response(request)

        idempotency_key = request.headers.get('Idempotency-Key')
        if not idempotency_key:
            return self.get_response(request)

        # Build a merchant-scoped cache key
        api_key = self._get_api_key(request)
        merchant_scope = api_key[:20] if api_key else 'anon'
        cache_key = f'idempotency:{merchant_scope}:{idempotency_key}'

        # Check cache — return stored response if exists
        cached = cache.get(cache_key)
        if cached:
            response = JsonResponse(cached['body'], status=cached['status'])
            response['X-Idempotency-Replayed'] = 'true'
            return response

        # Process the request normally
        response = self.get_response(request)

        # Cache successful responses only (2xx)
        if 200 <= response.status_code < 300:
            try:
                body = json.loads(response.content)
                cache.set(cache_key, {
                    'body': body,
                    'status': response.status_code,
                }, self.CACHE_TTL)
            except (json.JSONDecodeError, Exception):
                pass

        return response

    def _get_api_key(self, request):
        key = request.META.get('HTTP_X_API_KEY')
        if key:
            return key
        import base64
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if auth.startswith('Basic '):
            try:
                decoded = base64.b64decode(auth[6:]).decode('utf-8')
                return decoded.split(':')[0]
            except Exception:
                pass
        return None
