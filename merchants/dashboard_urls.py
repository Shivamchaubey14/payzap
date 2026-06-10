from django.urls import path
from merchants.dashboard_views import (
    dashboard_home,
    payments_list,
    payment_detail,
    dashboard_login,
    dashboard_logout,
)

urlpatterns = [
    path('', dashboard_home, name='dashboard-home'),
    path('payments/', payments_list, name='dashboard-payments'),
    path('payments/<uuid:payment_id>/', payment_detail, name='dashboard-payment-detail'),
    path('login/', dashboard_login, name='dashboard-login'),
    path('logout/', dashboard_logout, name='dashboard-logout'),
]