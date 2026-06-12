"""
PayZap - urls.py
Place this file inside payzap_core/ folder (replaces the existing urls.py)
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from django.views.generic import TemplateView

urlpatterns = [
    path('', include('django_prometheus.urls')),
    # Admin
    path('admin/', admin.site.urls),

    # API Docs (auto-generated from your DRF views)
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # App routes (will add more as we build each day)
    path('v1/', include('merchants.urls')),
    path('v1/', include('merchants.kyc_urls')),
    path('v1/', include('payments.urls')),
    path('pay/', include('payments.checkout_urls')),
    path('v1/', include('settlements.urls')),
    path('v1/', include('payouts.urls')),
    path('v1/', include('fraud.urls')),
    path('v1/', include('webhooks.urls')),
    path('dashboard/', include('merchants.dashboard_urls')),
    path('admin-panel/', include('admin_panel.urls')),
    path('monitoring/', include('monitoring.urls')),
    path('', TemplateView.as_view(template_name='landing/index.html'), name='landing'),
    path('onboarding/', TemplateView.as_view(template_name='onboarding/wizard.html'), name='onboarding'),
    path('status/', TemplateView.as_view(template_name='status/index.html'), name='status'),
]
