from django.urls import path
from merchants.views import (
    MerchantRegistrationView,
    MerchantLoginView,
    MerchantProfileView,
    GenerateAPIKeyView,
    EmailVerificationView,
)

urlpatterns = [
    path('accounts/register/', MerchantRegistrationView.as_view(), name='merchant-register'),
    path('accounts/login/', MerchantLoginView.as_view(), name='merchant-login'),
    path('accounts/me/', MerchantProfileView.as_view(), name='merchant-profile'),
    path('accounts/api-keys/', GenerateAPIKeyView.as_view(), name='generate-api-key'),
    path('accounts/verify-email/', EmailVerificationView.as_view(), name='verify-email'),
]