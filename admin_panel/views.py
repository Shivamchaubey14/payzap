import redis
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum, Count, Q
from datetime import timedelta
from django.conf import settings
from merchants.models import Merchant
from payments.models import Payment, Order
from settlements.models import Settlement
from webhooks.models import WebhookEvent
from fraud.models import FraudSignal


@staff_member_required
def platform_analytics(request):
    today = timezone.now().date()
    last_7 = today - timedelta(days=7)

    # GMV stats
    total_gmv = Payment.objects.filter(
        status='captured'
    ).aggregate(s=Sum('amount'))['s'] or 0

    today_gmv = Payment.objects.filter(
        status='captured',
        created_at__date=today,
    ).aggregate(s=Sum('amount'))['s'] or 0

    # Success rate today
    today_total = Payment.objects.filter(created_at__date=today).count()
    today_captured = Payment.objects.filter(
        status='captured', created_at__date=today
    ).count()
    success_rate = (today_captured / today_total * 100) if today_total else 0

    # Merchant stats
    total_merchants = Merchant.objects.count()
    live_merchants = Merchant.objects.filter(is_live=True).count()
    pending_kyc = Merchant.objects.filter(
        kyc_status__in=('submitted', 'under_review')
    ).count()

    # Fraud stats
    fraud_today = FraudSignal.objects.filter(
        created_at__date=today
    ).count()
    pending_review = FraudSignal.objects.filter(
        status='pending_review'
    ).count()

    # Webhook health
    dead_letters = WebhookEvent.objects.filter(status='dead_letter').count()
    failed_webhooks = WebhookEvent.objects.filter(status='failed').count()

    # Settlement stats
    pending_settlements = Settlement.objects.filter(
        status__in=('pending', 'processing')
    ).aggregate(s=Sum('amount'))['s'] or 0

    # Last 7 days revenue
    daily_revenue = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        rev = Payment.objects.filter(
            status='captured',
            created_at__date=day,
        ).aggregate(s=Sum('amount'))['s'] or 0
        daily_revenue.append({
            'date': day.strftime('%d %b'),
            'amount': rev / 100,
        })

    # Redis health
    redis_info = {}
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        info = r.info()
        redis_info = {
            'connected': True,
            'used_memory': info.get('used_memory_human', 'N/A'),
            'connected_clients': info.get('connected_clients', 0),
            'uptime_days': info.get('uptime_in_days', 0),
        }
    except Exception:
        redis_info = {'connected': False}

    return render(request, 'admin_panel/analytics.html', {
        'total_gmv': total_gmv / 100,
        'today_gmv': today_gmv / 100,
        'success_rate': round(success_rate, 1),
        'total_merchants': total_merchants,
        'live_merchants': live_merchants,
        'pending_kyc': pending_kyc,
        'fraud_today': fraud_today,
        'pending_review': pending_review,
        'dead_letters': dead_letters,
        'failed_webhooks': failed_webhooks,
        'pending_settlements': pending_settlements / 100,
        'daily_revenue': daily_revenue,
        'redis_info': redis_info,
    })


@staff_member_required
def merchant_management(request):
    merchants = Merchant.objects.order_by('-created_at')

    search = request.GET.get('q')
    kyc_filter = request.GET.get('kyc_status')
    if search:
        merchants = merchants.filter(
            Q(business_name__icontains=search) |
            Q(email__icontains=search)
        )
    if kyc_filter:
        merchants = merchants.filter(kyc_status=kyc_filter)

    # Handle fee rate update
    if request.method == 'POST':
        merchant_id = request.POST.get('merchant_id')
        fee_rate = request.POST.get('fee_rate')
        action = request.POST.get('action')

        if merchant_id and fee_rate:
            try:
                Merchant.objects.filter(id=merchant_id).update(
                    fee_rate=float(fee_rate)
                )
            except ValueError:
                pass

        if merchant_id and action == 'suspend':
            Merchant.objects.filter(id=merchant_id).update(is_active=False)
        elif merchant_id and action == 'unsuspend':
            Merchant.objects.filter(id=merchant_id).update(is_active=True)

    return render(request, 'admin_panel/merchants.html', {
        'merchants': merchants,
        'search': search or '',
        'kyc_filter': kyc_filter or '',
    })