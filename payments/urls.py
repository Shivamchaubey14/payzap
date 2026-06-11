from django.urls import path

from payments.views import (
    BankListView,
    OrderCreateView,
    OrderDetailView,
    OrderListView,
    PaymentCaptureView,
    PaymentCreateView,
    PaymentDetailView,
    PaymentLinkCreateView,
    PaymentLinkDetailView,
    PaymentLinkListView,
    RefundCreateView,
    RefundDetailView,
    VirtualAccountCreateView,
    VirtualAccountCreditView,
    VirtualAccountDetailView,
)

urlpatterns = [
    path('banks/', BankListView.as_view(), name='bank-list'),
    path('orders/', OrderListView.as_view(), name='order-list'),
    path('orders/create/', OrderCreateView.as_view(), name='order-create'),
    path('orders/<uuid:order_id>/', OrderDetailView.as_view(), name='order-detail'),
    path('payments/', PaymentCreateView.as_view(), name='payment-create'),
    path('payments/<uuid:payment_id>/', PaymentDetailView.as_view(), name='payment-detail'),
    path('payments/<uuid:payment_id>/capture/', PaymentCaptureView.as_view(), name='payment-capture'),
    path('refunds/', RefundCreateView.as_view(), name='refund-create'),
    path('refunds/<uuid:refund_id>/', RefundDetailView.as_view(), name='refund-detail'),
    path('payment_links/', PaymentLinkListView.as_view(), name='payment-link-list'),
    path('payment_links/create/', PaymentLinkCreateView.as_view(), name='payment-link-create'),
    path('payment_links/<uuid:link_id>/', PaymentLinkDetailView.as_view(), name='payment-link-detail'),
    path('virtual_accounts/', VirtualAccountCreateView.as_view(), name='virtual-account-create'),
    path('virtual_accounts/<uuid:va_id>/', VirtualAccountDetailView.as_view(), name='virtual-account-detail'),
    path('virtual_accounts/<uuid:va_id>/credit/', VirtualAccountCreditView.as_view(), name='virtual-account-credit'),
]
