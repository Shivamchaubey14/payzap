import logging
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, name='payments.send_confirmation_email')
def send_payment_confirmation_email(self, payment_id: str):
    """
    Sends payment confirmation email to the customer.
    Triggered after a payment is captured.
    """
    try:
        from payments.models import Payment
        payment = Payment.objects.select_related('order__merchant').get(id=payment_id)

        merchant = payment.order.merchant
        amount_rupees = payment.amount / 100

        send_mail(
            subject=f'Payment Confirmed — ₹{amount_rupees:.2f}',
            message=(
                f'Your payment of ₹{amount_rupees:.2f} to '
                f'{merchant.business_name} was successful.\n'
                f'Payment ID: {payment.id}\n'
                f'Transaction ID: {payment.gateway_txn_id}'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[merchant.email],
            html_message=f'''
                <h2>Payment Successful ✅</h2>
                <p>Your payment of <strong>₹{amount_rupees:.2f}</strong>
                to <strong>{merchant.business_name}</strong> was successful.</p>
                <table>
                  <tr><td>Payment ID</td><td>{payment.id}</td></tr>
                  <tr><td>Amount</td><td>₹{amount_rupees:.2f}</td></tr>
                  <tr><td>Status</td><td>{payment.status}</td></tr>
                  <tr><td>Transaction ID</td><td>{payment.gateway_txn_id}</td></tr>
                </table>
            ''',
        )
        logger.info(f"Confirmation email sent for payment {payment_id}")

    except Exception as exc:
        logger.error(f"Failed to send confirmation email for {payment_id}: {exc}")
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=24, name='payments.poll_payment_status')
def poll_payment_status(self, payment_id: str):
    """
    Polls gateway every 30s for async payment methods (UPI, net banking).
    Gives up after 24 retries (= ~12 minutes total).
    """
    try:
        from payments.models import Payment
        from payments.processors.mock_gateway import MockBankGateway
        from django.db import transaction

        payment = Payment.objects.select_for_update().get(id=payment_id)

        if payment.status in ('captured', 'failed', 'refunded'):
            logger.info(f"Payment {payment_id} already in terminal state: {payment.status}")
            return

        gateway = MockBankGateway()
        result = gateway.check_status(payment.gateway_txn_id)

        with transaction.atomic():
            if result.success and result.status == 'captured':
                payment.status = 'captured'
                payment.captured_at = timezone.now()
                payment.save()

                from payments.models import Order
                Order.objects.filter(id=payment.order_id).update(status='paid')

                # Fire webhook and email
                from webhooks.tasks import dispatch_webhook_event
                dispatch_webhook_event.delay(
                    str(payment.order.merchant_id),
                    'payment.captured',
                    {'payment_id': str(payment.id), 'amount': payment.amount}
                )
                send_payment_confirmation_email.delay(str(payment.id))
                logger.info(f"Payment {payment_id} captured via polling")
                return

        # Not yet complete — retry after 30 seconds
        raise self.retry(countdown=30)

    except Exception as exc:
        if not isinstance(exc, self.retry.__class__):
            logger.error(f"Polling error for payment {payment_id}: {exc}")
        raise


@shared_task(name='payments.expire_stale_orders')
def expire_stale_orders():
    """
    Runs every 5 minutes via Celery Beat.
    Expires orders that passed their expiry time without payment.
    """
    from payments.models import Order

    expired = Order.objects.filter(
        status__in=('created', 'attempted'),
        expires_at__lt=timezone.now(),
    )
    count = expired.update(status='expired')
    if count:
        logger.info(f"Expired {count} stale orders")