from django.urls import path

from admin_panel.views import merchant_management, platform_analytics

urlpatterns = [
    path('analytics/', platform_analytics, name='admin-analytics'),
    path('merchants/', merchant_management, name='admin-merchants'),
]
