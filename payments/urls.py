from django.urls import path
from payments.views import (
    OrderCreateView, OrderDetailView, OrderListView,
    PaymentCreateView, PaymentDetailView, PaymentCaptureView,BankListView
)

urlpatterns = [
    path('banks/', BankListView.as_view(), name='bank-list'),
    path('orders/', OrderListView.as_view(), name='order-list'),
    path('orders/create/', OrderCreateView.as_view(), name='order-create'),
    path('orders/<uuid:order_id>/', OrderDetailView.as_view(), name='order-detail'),
    path('payments/', PaymentCreateView.as_view(), name='payment-create'),
    path('payments/<uuid:payment_id>/', PaymentDetailView.as_view(), name='payment-detail'),
    path('payments/<uuid:payment_id>/capture/', PaymentCaptureView.as_view(), name='payment-capture'),
]