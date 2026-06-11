from django.urls import path

from merchants.kyc_views import (
    KYCAdminReviewView,
    KYCStatusView,
    KYCSubmitView,
    KYCUpdateBankView,
    KYCUploadURLView,
)

urlpatterns = [
    path('kyc/upload-url/', KYCUploadURLView.as_view(), name='kyc-upload-url'),
    path('kyc/status/', KYCStatusView.as_view(), name='kyc-status'),
    path('kyc/submit/', KYCSubmitView.as_view(), name='kyc-submit'),
    path('kyc/review/', KYCAdminReviewView.as_view(), name='kyc-review'),
    path('kyc/bank/', KYCUpdateBankView.as_view(), name='kyc-bank'),
]
