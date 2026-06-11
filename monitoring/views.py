from datetime import timedelta

import redis
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone

from merchants.models import Merchant
from payments.models import Payment
from settlements.models import Settlement
from webhooks.models import WebhookEvent


@staff_member_required
def health_check(request):
    """
    GET /monitoring/health/
    Returns system health status for all components.
    """
    health = {
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'components': {}
    }

    # Database check
    try:
        Merchant.objects.count()
        health['components']['database'] = {'status': 'healthy'}
    except Exception as e:
        health['components']['database'] = {'status': 'unhealthy', 'error': str(e)}
        health['status'] = 'degraded'

    # Redis check
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.ping()
        info = r.info()
        health['components']['redis'] = {
            'status': 'healthy',
            'used_memory': info.get('used_memory_human'),
            'connected_clients': info.get('connected_clients'),
        }
    except Exception as e:
        health['components']['redis'] = {'status': 'unhealthy', 'error': str(e)}
        health['status'] = 'degraded'

    # Payment success rate (last 1 hour)
    try:
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent = Payment.objects.filter(created_at__gte=one_hour_ago)
        total = recent.count()
        captured = recent.filter(status='captured').count()
        success_rate = (captured / total * 100) if total else 100

        health['components']['payments'] = {
            'status': 'healthy' if success_rate >= 95 else 'degraded',
            'success_rate_1h': round(success_rate, 2),
            'total_1h': total,
        }
        if success_rate < 95:
            health['status'] = 'degraded'
    except Exception as e:
        health['components']['payments'] = {'status': 'unknown', 'error': str(e)}

    # Webhook queue health
    try:
        dead_letters = WebhookEvent.objects.filter(status='dead_letter').count()
        failed = WebhookEvent.objects.filter(status='failed').count()
        health['components']['webhooks'] = {
            'status': 'healthy' if dead_letters < 100 else 'degraded',
            'dead_letters': dead_letters,
            'failed': failed,
        }
    except Exception as e:
        health['components']['webhooks'] = {'status': 'unknown', 'error': str(e)}

    status_code = 200 if health['status'] == 'healthy' else 207
    return JsonResponse(health, status=status_code)


@staff_member_required
def system_stats(request):
    """
    GET /monitoring/stats/
    Returns live platform statistics.
    """
    today = timezone.now().date()

    today_payments = Payment.objects.filter(created_at__date=today)
    total = today_payments.count()
    captured = today_payments.filter(status='captured').count()

    stats = {
        'timestamp': timezone.now().isoformat(),
        'payments': {
            'today_total': total,
            'today_captured': captured,
            'today_failed': today_payments.filter(status='failed').count(),
            'today_gmv_paise': today_payments.filter(
                status='captured'
            ).aggregate(s=Sum('amount'))['s'] or 0,
            'success_rate_today': round((captured / total * 100) if total else 0, 2),
        },
        'merchants': {
            'total': Merchant.objects.count(),
            'active': Merchant.objects.filter(is_active=True).count(),
            'live': Merchant.objects.filter(is_live=True).count(),
        },
        'webhooks': {
            'dead_letters': WebhookEvent.objects.filter(status='dead_letter').count(),
            'pending_retry': WebhookEvent.objects.filter(status='failed').count(),
        },
        'settlements': {
            'pending_amount_paise': Settlement.objects.filter(
                status__in=('pending', 'processing')
            ).aggregate(s=Sum('amount'))['s'] or 0,
        },
    }

    return JsonResponse(stats)
