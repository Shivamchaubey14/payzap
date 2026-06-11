import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, name='merchants.kyc.submitted')
def send_kyc_submitted_email(self, merchant_id: str):
    try:
        from merchants.models import Merchant
        merchant = Merchant.objects.get(id=merchant_id)
        send_mail(
            subject='KYC Documents Received — PayZap',
            message=(
                f'Hi {merchant.business_name},\n\n'
                'We have received your KYC documents. '
                'Our team will review them within 1-2 business days.\n\n'
                'You will be notified once the review is complete.\n\n'
                'PayZap Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[merchant.email],
            html_message=f'''
                <h2>KYC Documents Received ✅</h2>
                <p>Hi <strong>{merchant.business_name}</strong>,</p>
                <p>We have received your KYC documents.
                Our team will review them within <strong>1-2 business days</strong>.</p>
                <p>You will be notified via email once the review is complete.</p>
                <br><p>— PayZap Team</p>
            ''',
        )
        logger.info(f"KYC submitted email sent to {merchant.email}")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc


@shared_task(bind=True, max_retries=3, name='merchants.kyc.approved')
def send_kyc_approved_email(self, merchant_id: str):
    try:
        from merchants.models import Merchant
        merchant = Merchant.objects.get(id=merchant_id)
        send_mail(
            subject='🎉 KYC Approved — You are now live on PayZap!',
            message=(
                f'Hi {merchant.business_name},\n\n'
                'Congratulations! Your KYC has been approved. '
                'Your account is now live and you can start accepting real payments.\n\n'
                'Log in to your dashboard to get your live API keys.\n\n'
                'PayZap Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[merchant.email],
            html_message=f'''
                <h2>KYC Approved 🎉</h2>
                <p>Hi <strong>{merchant.business_name}</strong>,</p>
                <p>Congratulations! Your KYC has been approved and your account is now
                <strong>LIVE</strong>.</p>
                <p>You can now accept real payments. Log in to your dashboard to get
                your live API keys.</p>
                <br><p>— PayZap Team</p>
            ''',
        )
        logger.info(f"KYC approval email sent to {merchant.email}")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc


@shared_task(bind=True, max_retries=3, name='merchants.kyc.rejected')
def send_kyc_rejected_email(self, merchant_id: str, reason: str):
    try:
        from merchants.models import Merchant
        merchant = Merchant.objects.get(id=merchant_id)
        send_mail(
            subject='KYC Review Update — Action Required',
            message=(
                f'Hi {merchant.business_name},\n\n'
                f'Unfortunately, your KYC documents could not be approved.\n\n'
                f'Reason: {reason}\n\n'
                'Please log in to your dashboard, re-upload the required documents, '
                'and resubmit for review.\n\n'
                'PayZap Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[merchant.email],
            html_message=f'''
                <h2>KYC Review Update</h2>
                <p>Hi <strong>{merchant.business_name}</strong>,</p>
                <p>Unfortunately, your KYC documents could not be approved.</p>
                <p><strong>Reason:</strong> {reason}</p>
                <p>Please log in to your dashboard, re-upload the required documents,
                and resubmit for review.</p>
                <br><p>— PayZap Team</p>
            ''',
        )
        logger.info(f"KYC rejection email sent to {merchant.email}")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc
