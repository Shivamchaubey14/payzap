from django.urls import path

from payments.views import PaymentLinkCheckoutView

urlpatterns = [
    path('<slug:slug>/', PaymentLinkCheckoutView.as_view(), name='payment-link-checkout'),
]
