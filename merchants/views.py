import jwt
import secrets
import hashlib
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from merchants.models import Merchant, APIKey
from merchants.serializers import MerchantRegistrationSerializer, MerchantProfileSerializer
from merchants.authentication import APIKeyAuthentication


class MerchantRegistrationView(APIView):
    """
    POST /v1/accounts/register
    Creates merchant account + Django user + sends verification email.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MerchantRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # Create Django User for dashboard login
        user = User.objects.create_user(
            username=data['email'],
            email=data['email'],
            password=data['password'],
            is_active=False,  # Inactive until email verified
        )

        # Create Merchant profile
        merchant = Merchant.objects.create(
            business_name=data['business_name'],
            email=data['email'],
            phone=data['phone'],
            pan=data.get('pan', ''),
            gstin=data.get('gstin', ''),
        )

        # Auto-generate test API key
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'payments': True, 'refunds': True, 'webhooks': True},
        )

        # Send verification email via Celery
        try:
            from merchants.tasks import send_verification_email
            send_verification_email.delay(user.id, merchant.id)
        except Exception:
            pass  # Don't fail registration if email fails

        return Response({
            'message': 'Account created. Check your email to verify.',
            'merchant_id': str(merchant.id),
            'test_api_key': full_key,  # Only shown once at registration
        }, status=status.HTTP_201_CREATED)


class MerchantLoginView(APIView):
    """
    POST /v1/accounts/login
    Returns JWT access + refresh tokens for dashboard use.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').lower()
        password = request.data.get('password', '')

        if not email or not password:
            return Response(
                {'error': 'Email and password are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(username=email, password=password)
        if not user:
            return Response(
                {'error': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {'error': 'Please verify your email before logging in.'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            merchant = Merchant.objects.get(email=email)
        except Merchant.DoesNotExist:
            return Response({'error': 'Merchant not found.'}, status=status.HTTP_404_NOT_FOUND)

        refresh = RefreshToken.for_user(user)

        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'merchant': MerchantProfileSerializer(merchant).data,
        })


class MerchantProfileView(APIView):
    """
    GET /v1/accounts/me
    Returns merchant profile. Supports both API key and JWT auth.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if isinstance(request.user, Merchant):
            merchant = request.user
        else:
            try:
                merchant = Merchant.objects.get(email=request.user.email)
            except Merchant.DoesNotExist:
                return Response({'error': 'Not found.'}, status=404)

        return Response(MerchantProfileSerializer(merchant).data)


class GenerateAPIKeyView(APIView):
    """
    POST /v1/accounts/api-keys
    Generates a new API key for the authenticated merchant.
    """
    authentication_classes = [APIKeyAuthentication]

    def post(self, request):
        merchant = request.user
        is_live = request.data.get('is_live', False)

        if is_live and merchant.kyc_status != 'approved':
            return Response(
                {'error': 'KYC must be approved before generating live keys.'},
                status=status.HTTP_403_FORBIDDEN
            )

        full_key, prefix, key_hash = APIKey.generate_key(is_live=is_live)
        api_key = APIKey.objects.create(
            merchant=merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=is_live,
            permissions={'payments': True, 'refunds': True, 'webhooks': True},
        )

        return Response({
            'key': full_key,  # Shown only once — merchant must save it
            'prefix': prefix,
            'is_live': is_live,
            'created_at': api_key.created_at,
            'warning': 'Save this key now. It will not be shown again.',
        }, status=status.HTTP_201_CREATED)
        
class EmailVerificationView(APIView):
    """
    GET /v1/accounts/verify-email/?token=xxx
    Activates merchant account after email verification.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get('token')
        if not token:
            return Response({'error': 'Token is required.'}, status=400)

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            if payload.get('type') != 'email_verification':
                raise ValueError('Invalid token type.')

            user = User.objects.get(id=payload['user_id'])
            user.is_active = True
            user.save()

            return Response({'message': 'Email verified. You can now log in.'})

        except jwt.ExpiredSignatureError:
            return Response({'error': 'Verification link has expired.'}, status=400)
        except (jwt.InvalidTokenError, User.DoesNotExist, ValueError):
            return Response({'error': 'Invalid verification token.'}, status=400)