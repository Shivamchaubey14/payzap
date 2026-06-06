import uuid
from django.test import TestCase
from merchants.models import Merchant
from payments.models import Order, Payment


class OrderModelTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name="Pay Corp",
            email="pay@paycorp.com",
            phone="7777777777",
        )

    def test_order_created_with_uuid(self):
        order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,  # ₹500
            currency='INR',
            idempotency_key=str(uuid.uuid4()),
        )
        self.assertIsNotNone(order.id)

    def test_default_status_is_created(self):
        order = Order.objects.create(
            merchant=self.merchant,
            amount=10000,
            idempotency_key=str(uuid.uuid4()),
        )
        self.assertEqual(order.status, 'created')

    def test_amount_in_rupees_property(self):
        order = Order.objects.create(
            merchant=self.merchant,
            amount=100000,  # ₹1000
            idempotency_key=str(uuid.uuid4()),
        )
        self.assertEqual(order.amount_in_rupees, 1000.0)

    def test_idempotency_key_is_unique(self):
        key = str(uuid.uuid4())
        Order.objects.create(
            merchant=self.merchant,
            amount=10000,
            idempotency_key=key,
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Order.objects.create(
                merchant=self.merchant,
                amount=20000,
                idempotency_key=key,  # Same key — must fail
            )

    def test_order_str(self):
        order = Order.objects.create(
            merchant=self.merchant,
            amount=25000,
            idempotency_key=str(uuid.uuid4()),
        )
        self.assertIn('₹', str(order))
        self.assertIn('created', str(order))


class PaymentModelTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name="Payments Co",
            email="pmts@co.com",
            phone="6666666666",
        )
        self.order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )

    def test_payment_created(self):
        payment = Payment.objects.create(
            order=self.order,
            method='card',
            amount=50000,
        )
        self.assertEqual(payment.status, 'created')
        self.assertEqual(payment.amount_refunded, 0)

    def test_refundable_amount(self):
        payment = Payment.objects.create(
            order=self.order,
            method='upi',
            amount=50000,
            amount_refunded=10000,
        )
        self.assertEqual(payment.refundable_amount, 40000)

    def test_payment_str(self):
        payment = Payment.objects.create(
            order=self.order,
            method='card',
            amount=50000,
        )
        self.assertIn('card', str(payment))
        self.assertIn('₹', str(payment))