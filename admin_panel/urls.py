from django.urls import path
from admin_panel.views import platform_analytics, merchant_management

urlpatterns = [
    path('analytics/', platform_analytics, name='admin-analytics'),
    path('merchants/', merchant_management, name='admin-merchants'),
]