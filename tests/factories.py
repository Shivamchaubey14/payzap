import factory
import factory.django

from merchants.models import APIKey, Merchant
from payments.models import Order, Payment


class MerchantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Merchant

    email = factory.Sequence(lambda n: f'merchant_{n}@test.com')
    business_name = factory.Sequence(lambda n: f'Test Corp {n}')
    is_live = False
    fee_rate = 0.02


def _make_api_key_data():
    full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
    return full_key, prefix, key_hash


class APIKeyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = APIKey

    merchant = factory.SubFactory(MerchantFactory)
    is_live = False
    is_active = True
    key_prefix = ''
    key_hash = ''

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        kwargs['key_prefix'] = prefix
        kwargs['key_hash'] = key_hash
        instance = model_class.objects.create(**kwargs)
        instance.full_key = full_key  # attach for test use, not saved to DB
        return instance

class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    merchant = factory.SubFactory(MerchantFactory)
    amount = 50000
    currency = 'INR'
    status = 'created'
    receipt = factory.Sequence(lambda n: f'receipt_{n}')
    idempotency_key = factory.Sequence(lambda n: f'idem_key_{n}')


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment

    order = factory.SubFactory(OrderFactory)
    amount = 50000
    method = 'card'
    status = 'created'
    amount_refunded = 0
    in_settlement = False
