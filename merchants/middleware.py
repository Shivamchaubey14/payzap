import redis
from django.conf import settings
from django.http import JsonResponse


class APIKeyRateLimitMiddleware:
    """
    Rate limits API key requests to 1000 req/min.
    Uses Redis INCR + EXPIRE for atomic counting.
    """

    RATE_LIMIT = 1000       # requests
    WINDOW = 60             # seconds

    def __init__(self, get_response):
        self.get_response = get_response
        self.redis = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True
        )

    def __call__(self, request):
        # Only rate limit API endpoints
        if not request.path.startswith('/v1/'):
            return self.get_response(request)

        api_key = self._get_api_key(request)
        if not api_key:
            return self.get_response(request)

        # Use first 20 chars of key as Redis key identifier
        key_id = api_key[:20]
        redis_key = f"ratelimit:{key_id}"

        try:
            current = self.redis.incr(redis_key)
            if current == 1:
                self.redis.expire(redis_key, self.WINDOW)

            if current > self.RATE_LIMIT:
                ttl = self.redis.ttl(redis_key)
                return JsonResponse({
                    'error': 'rate_limit_exceeded',
                    'message': f'Too many requests. Limit: {self.RATE_LIMIT}/min.',
                    'retry_after': ttl,
                }, status=429)

            # Attach rate limit headers to response
            response = self.get_response(request)
            response['X-RateLimit-Limit'] = self.RATE_LIMIT
            response['X-RateLimit-Remaining'] = max(0, self.RATE_LIMIT - current)
            return response

        except redis.RedisError:
            # Redis down — fail open (don't block payments)
            return self.get_response(request)

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
