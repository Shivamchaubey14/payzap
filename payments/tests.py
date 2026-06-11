import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from merchants.models import APIKey, Merchant
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


class OrderAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        # Use unique email per test to avoid cross-test DB conflicts
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'Order Test Corp {unique}',
            email=f'orders_{unique}@corp.com',
            phone='9000000001',
        )
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'payments': True},
        )
        self.api_key = full_key

    def test_create_order_returns_201(self):
        response = self.client.post(
            '/v1/orders/create/',
            {'amount': 50000, 'currency': 'INR', 'receipt': 'rcpt_001'},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        print(f"\nDEBUG 201: status={response.status_code}, key={self.api_key[:30]}, data={response.data}")
        self.assertEqual(response.status_code, 201)

    def test_create_order_response_has_correct_fields(self):
        response = self.client.post(
            '/v1/orders/create/',
            {'amount': 50000, 'currency': 'INR'},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertIn('id', response.data)
        self.assertIn('amount_in_rupees', response.data)
        self.assertEqual(response.data['status'], 'created')
        self.assertEqual(response.data['amount_in_rupees'], 500.0)

    def test_create_order_amount_zero_returns_400(self):
        response = self.client.post(
            '/v1/orders/create/',
            {'amount': 0, 'currency': 'INR'},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)

    def test_create_order_below_minimum_returns_400(self):
        response = self.client.post(
            '/v1/orders/create/',
            {'amount': 50, 'currency': 'INR'},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)

    def test_create_order_invalid_currency_returns_400(self):
        response = self.client.post(
            '/v1/orders/create/',
            {'amount': 50000, 'currency': 'GBP'},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_idempotency_key_returns_existing_order(self):
        idem_key = str(uuid.uuid4())
        response1 = self.client.post(
            '/v1/orders/create/',
            {'amount': 50000, 'currency': 'INR', 'idempotency_key': idem_key},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        response2 = self.client.post(
            '/v1/orders/create/',
            {'amount': 50000, 'currency': 'INR', 'idempotency_key': idem_key},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response1.data['id'], response2.data['id'])
        self.assertEqual(Order.objects.filter(merchant=self.merchant).count(), 1)

    def test_get_order_returns_200(self):
        order = Order.objects.create(
            merchant=self.merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )
        response = self.client.get(
            f'/v1/orders/{order.id}/',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data['id']), str(order.id))

    def test_get_order_wrong_merchant_returns_403(self):
        other_merchant = Merchant.objects.create(
            business_name='Other Corp',
            email='other@corp.com',
            phone='7000000000',
        )
        order = Order.objects.create(
            merchant=other_merchant,
            amount=50000,
            idempotency_key=str(uuid.uuid4()),
        )
        response = self.client.get(
            f'/v1/orders/{order.id}/',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 403)

    def test_get_nonexistent_order_returns_404(self):
        response = self.client.get(
            f'/v1/orders/{uuid.uuid4()}/',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 404)

    def test_list_orders_returns_200(self):
        Order.objects.create(merchant=self.merchant, amount=10000, idempotency_key=str(uuid.uuid4()))
        Order.objects.create(merchant=self.merchant, amount=20000, idempotency_key=str(uuid.uuid4()))
        response = self.client.get(
            '/v1/orders/',
            **{'HTTP_X_API_KEY': self.api_key}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)

    def test_unauthenticated_request_returns_401(self):
        response = self.client.post(
            '/v1/orders/create/',
            {'amount': 50000, 'currency': 'INR'},
            format='json'
        )
        self.assertEqual(response.status_code, 401)
