from django.urls import path
from payments.views import OrderCreateView, OrderDetailView, OrderListView

urlpatterns = [
    path('orders/', OrderListView.as_view(), name='order-list'),
    path('orders/create/', OrderCreateView.as_view(), name='order-create'),
    path('orders/<uuid:order_id>/', OrderDetailView.as_view(), name='order-detail'),
]