from django.urls import path

from merchants.dashboard_views import (
    dashboard_home,
    dashboard_login,
    dashboard_logout,
    payment_detail,
    payments_list,
    sandbox,
)

urlpatterns = [
    path('', dashboard_home, name='dashboard-home'),
    path('payments/', payments_list, name='dashboard-payments'),
    path('payments/<uuid:payment_id>/', payment_detail, name='dashboard-payment-detail'),
    path('login/', dashboard_login, name='dashboard-login'),
    path('logout/', dashboard_logout, name='dashboard-logout'),
    path('sandbox/', sandbox, name='dashboard-sandbox'),
]
