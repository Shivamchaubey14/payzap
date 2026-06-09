import uuid
from rest_framework import serializers
from payments.models import Order, Payment


class OrderCreateSerializer(serializers.ModelSerializer):
    idempotency_key = serializers.CharField(required=False, max_length=255)
    notes = serializers.JSONField(required=False, default=dict)

    class Meta:
        model = Order
        fields = ['amount', 'currency', 'receipt', 'notes', 'idempotency_key']

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than 0.')
        if value < 100:
            raise serializers.ValidationError('Minimum amount is ₹1 (100 paise).')
        if value > 10000000:  # ₹1,00,000 max per transaction
            raise serializers.ValidationError('Amount exceeds maximum limit of ₹1,00,000.')
        return value

    def validate_currency(self, value):
        allowed = ['INR', 'USD', 'EUR']
        if value not in allowed:
            raise serializers.ValidationError(f'Currency must be one of: {", ".join(allowed)}')
        return value

    def validate(self, data):
        # Auto-generate idempotency key if not provided
        if not data.get('idempotency_key'):
            data['idempotency_key'] = str(uuid.uuid4())
        return data


class OrderResponseSerializer(serializers.ModelSerializer):
    amount_in_rupees = serializers.ReadOnlyField()
    merchant_id = serializers.UUIDField(source='merchant.id', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'merchant_id', 'amount', 'amount_in_rupees',
            'currency', 'status', 'receipt', 'notes',
            'idempotency_key', 'created_at', 'expires_at'
        ]


class PaymentResponseSerializer(serializers.ModelSerializer):
    order_id = serializers.UUIDField(source='order.id', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'order_id', 'method', 'status',
            'amount', 'currency', 'gateway_txn_id',
            'amount_refunded', 'captured_at', 'failed_at',
            'failure_reason', 'card_network', 'card_last4',
            'bank', 'is_3ds', 'three_ds_url', 'created_at'
        ]