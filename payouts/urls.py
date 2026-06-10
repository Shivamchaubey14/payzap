from django.urls import path
from payouts.views import PayoutCreateView, PayoutBulkView, PayoutDetailView, PayoutListView

urlpatterns = [
    path('payouts/', PayoutListView.as_view(), name='payout-list'),
    path('payouts/create/', PayoutCreateView.as_view(), name='payout-create'),
    path('payouts/bulk/', PayoutBulkView.as_view(), name='payout-bulk'),
    path('payouts/<uuid:payout_id>/', PayoutDetailView.as_view(), name='payout-detail'),
]