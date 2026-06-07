from rest_framework import serializers
from merchants.models import Merchant


class MerchantRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = Merchant
        fields = [
            'business_name', 'email', 'phone',
            'pan', 'gstin', 'password', 'confirm_password'
        ]

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return data

    def validate_email(self, value):
        if Merchant.objects.filter(email=value).exists():
            raise serializers.ValidationError('A merchant with this email already exists.')
        return value.lower()

    def validate_pan(self, value):
        import re
        if value and not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]$', value):
            raise serializers.ValidationError('Invalid PAN format. Expected: ABCDE1234F')
        return value.upper() if value else value


class MerchantProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = [
            'id', 'business_name', 'email', 'phone',
            'pan', 'gstin', 'kyc_status', 'is_live',
            'fee_rate', 'created_at'
        ]
        read_only_fields = ['id', 'kyc_status', 'is_live', 'fee_rate', 'created_at']