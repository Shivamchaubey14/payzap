import json
from datetime import timedelta
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.utils import timezone
from django.db.models import Sum, Count, Q
from payments.models import Payment, Order
from merchants.models import Merchant


def get_merchant(request):
    try:
        return Merchant.objects.get(email=request.user.email)
    except Merchant.DoesNotExist:
        return None


@login_required(login_url='/dashboard/login/')
def dashboard_home(request):
    merchant = get_merchant(request)
    if not merchant:
        return redirect('/dashboard/login/')

    today = timezone.now().date()

    # Today's stats
    today_payments = Payment.objects.filter(
        order__merchant=merchant,
        created_at__date=today,
    )

    total_transactions = today_payments.count()
    captured = today_payments.filter(status='captured')
    failed_transactions = today_payments.filter(status='failed').count()

    today_gmv = (captured.aggregate(s=Sum('amount'))['s'] or 0) / 100
    success_rate = (captured.count() / total_transactions * 100) if total_transactions else 0
    settlement_due = today_gmv * (1 - float(merchant.fee_rate))

    # Last 7 days revenue chart
    labels, data = [], []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        rev = Payment.objects.filter(
            order__merchant=merchant,
            status='captured',
            created_at__date=day,
        ).aggregate(s=Sum('amount'))['s'] or 0
        labels.append(day.strftime('%d %b'))
        data.append(rev)

    # Payment method breakdown
    method_qs = Payment.objects.filter(
        order__merchant=merchant,
        status='captured',
    ).values('method').annotate(total=Count('id'))

    method_labels = [m['method'].upper() for m in method_qs]
    method_data = [m['total'] for m in method_qs]

    # Recent payments
    recent = Payment.objects.filter(
        order__merchant=merchant
    ).order_by('-created_at')[:10]

    recent_payments = [{
        'id': str(p.id),
        'amount_rupees': f'{p.amount/100:.2f}',
        'method': p.method,
        'status': p.status,
        'created_at': p.created_at,
    } for p in recent]

    return render(request, 'dashboard/home.html', {
        'merchant': merchant,
        'today_gmv': today_gmv,
        'success_rate': success_rate,
        'total_transactions': total_transactions,
        'failed_transactions': failed_transactions,
        'settlement_due': settlement_due,
        'chart_labels': json.dumps(labels),
        'chart_data': json.dumps(data),
        'method_labels': json.dumps(method_labels),
        'method_data': json.dumps(method_data),
        'recent_payments': recent_payments,
    })


@login_required(login_url='/dashboard/login/')
def payments_list(request):
    merchant = get_merchant(request)
    if not merchant:
        return redirect('/dashboard/login/')

    queryset = Payment.objects.filter(
        order__merchant=merchant
    ).order_by('-created_at')

    # Filters
    status = request.GET.get('status')
    method = request.GET.get('method')
    from_date = request.GET.get('from')
    to_date = request.GET.get('to')

    if status:
        queryset = queryset.filter(status=status)
    if method:
        queryset = queryset.filter(method=method)
    if from_date:
        queryset = queryset.filter(created_at__date__gte=from_date)
    if to_date:
        queryset = queryset.filter(created_at__date__lte=to_date)

    total_count = queryset.count()
    page = int(request.GET.get('page', 1))
    page_size = 20
    start = (page - 1) * page_size
    total_pages = (total_count + page_size - 1) // page_size

    payments = [{
        'id': str(p.id),
        'order_id': str(p.order_id),
        'amount_rupees': f'{p.amount/100:.2f}',
        'method': p.method,
        'status': p.status,
        'gateway_txn_id': p.gateway_txn_id,
        'created_at': p.created_at,
    } for p in queryset[start:start + page_size]]

    return render(request, 'dashboard/payments.html', {
        'merchant': merchant,
        'payments': payments,
        'total_count': total_count,
        'page': page,
        'total_pages': total_pages,
    })


@login_required(login_url='/dashboard/login/')
def payment_detail(request, payment_id):
    merchant = get_merchant(request)
    if not merchant:
        return redirect('/dashboard/login/')

    try:
        payment = Payment.objects.get(id=payment_id, order__merchant=merchant)
    except Payment.DoesNotExist:
        return redirect('/dashboard/payments/')

    return render(request, 'dashboard/payment_detail.html', {
        'merchant': merchant,
        'payment': payment,
        'gateway_response': json.dumps(payment.gateway_response, indent=2),
    })


def dashboard_login(request):
    from django.contrib.auth import authenticate, login
    from django.contrib.auth.forms import AuthenticationForm

    if request.user.is_authenticated:
        return redirect('/dashboard/')

    error = None
    if request.method == 'POST':
        email = request.POST.get('username')
        password = request.POST.get('password')
        from django.contrib.auth.models import User as DjangoUser
        try:
            django_user = DjangoUser.objects.get(email=email)
            user = authenticate(request, username=django_user.username, password=password)
        except DjangoUser.DoesNotExist:
            user = None
        print(f"DEBUG email={email} password={password}")
        print(f"DEBUG django_user found: {django_user if 'django_user' in dir() else 'NOT FOUND'}")
        print(f"DEBUG authenticate result: {user}")
        if user:
            login(request, user)
            return redirect('/dashboard/')
        error = 'Invalid email or password.'

    return render(request, 'dashboard/login.html', {'error': error})


def dashboard_logout(request):
    logout(request)
    return redirect('/dashboard/login/')