from django.urls import path

from fraud.views import BINBlacklistView, FraudSignalListView

urlpatterns = [
    path('fraud/signals/', FraudSignalListView.as_view(), name='fraud-signals'),
    path('fraud/bin-blacklist/', BINBlacklistView.as_view(), name='bin-blacklist'),
]
