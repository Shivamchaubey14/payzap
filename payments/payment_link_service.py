import logging

from django.db import transaction

from merchants.models import Merchant
from payments.models import Order, PaymentLink

logger = logging.getLogger(__name__)


class PaymentLinkService:

    def create_link(self, merchant: Merchant, data: dict) -> PaymentLink:
        """Create a new payment link."""
        link = PaymentLink.objects.create(
            merchant=merchant,
            slug=PaymentLink.generate_slug(),
            amount=data.get('amount'),           # None = open amount
            currency=data.get('currency', 'INR'),
            description=data.get('description', ''),
            max_uses=data.get('max_uses'),
            expires_at=data.get('expires_at'),
            notes=data.get('notes', {}),
        )
        logger.info(f"PaymentLink {link.slug} created for merchant {merchant.id}")
        return link

    def get_link(self, slug: str) -> PaymentLink:
        """Fetch a link by slug — raises ValueError if not found."""
        try:
            return PaymentLink.objects.select_related('merchant').get(slug=slug)
        except PaymentLink.DoesNotExist:
            raise ValueError('Payment link not found.') from None

    @transaction.atomic
    def record_payment(self, link: PaymentLink, amount: int) -> Order:
        """
        Called when a customer pays via a payment link.
        Creates an Order, increments use_count, marks paid if max_uses hit.
        """
        if not link.is_usable:
            raise ValueError('This payment link is no longer active.')

        # Use link amount if fixed, otherwise use provided amount
        order_amount = link.amount if link.amount else amount
        if not order_amount or order_amount <= 0:
            raise ValueError('Amount is required for open payment links.')

        import uuid
        order = Order.objects.create(
            merchant=link.merchant,
            amount=order_amount,
            currency=link.currency,
            idempotency_key=str(uuid.uuid4()),
            notes={'payment_link_id': str(link.id), 'slug': link.slug},
        )

        # Increment use count
        PaymentLink.objects.filter(id=link.id).update(
            use_count=link.use_count + 1
        )

        # Auto-close if max_uses reached
        if link.max_uses and (link.use_count + 1) >= link.max_uses:
            PaymentLink.objects.filter(id=link.id).update(status='paid')

        link.refresh_from_db()
        return order

    def disable_link(self, link: PaymentLink, merchant: Merchant):
        if link.merchant != merchant:
            raise ValueError('Permission denied.')
        PaymentLink.objects.filter(id=link.id).update(status='disabled')
        link.refresh_from_db()
        return link
