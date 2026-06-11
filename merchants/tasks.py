import datetime

import jwt
from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail


@shared_task(bind=True, max_retries=3)
def send_verification_email(self, user_id, merchant_id):
    try:
        user = User.objects.get(id=user_id)

        # Generate verification JWT token (24h expiry)
        payload = {
            'user_id': user_id,
            'merchant_id': str(merchant_id),
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
            'type': 'email_verification',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
        verify_url = f"{settings.FRONTEND_URL}/verify-email/?token={token}"

        send_mail(
            subject='Verify your PayZap account',
            message=f'Click to verify your email: {verify_url}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=f'''
                <h2>Welcome to PayZap!</h2>
                <p>Click below to verify your email and activate your account.</p>
                <a href="{verify_url}" style="
                    background:#2563eb;color:white;padding:12px 24px;
                    border-radius:6px;text-decoration:none;display:inline-block;
                ">Verify Email</a>
                <p>This link expires in 24 hours.</p>
            ''',
        )
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc


@shared_task(bind=True, max_retries=3)
def send_welcome_email(self, merchant_id):
    try:
        from merchants.models import Merchant
        merchant = Merchant.objects.get(id=merchant_id)

        send_mail(
            subject='Welcome to PayZap — Your account is active!',
            message=f'Hi {merchant.business_name}, your PayZap account is ready.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[merchant.email],
        )
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc
