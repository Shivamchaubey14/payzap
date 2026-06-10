from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from merchants.authentication import APIKeyAuthentication
from fraud.models import FraudSignal
from fraud.fraud_engine import FraudEngine


class FraudSignalListView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        signals = FraudSignal.objects.filter(
            payment__order__merchant=request.user
        ).select_related('payment').order_by('-created_at')

        signal_status = request.query_params.get('status')
        if signal_status:
            signals = signals.filter(status=signal_status)

        page = int(request.query_params.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        total = signals.count()

        data = [{
            'id': str(s.id),
            'payment_id': str(s.payment_id),
            'rule_triggered': s.rule_triggered,
            'risk_score': s.risk_score,
            'action_taken': s.action_taken,
            'details': s.details,
            'status': s.status,
            'created_at': s.created_at,
        } for s in signals[start:end]]

        return Response({
            'count': total,
            'page': page,
            'total_pages': (total + page_size - 1) // page_size,
            'items': data,
        })


class BINBlacklistView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        card_bin = request.data.get('card_bin', '').strip()
        if not card_bin or len(card_bin) != 6 or not card_bin.isdigit():
            return Response(
                {'error': 'card_bin must be exactly 6 digits.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        FraudEngine.add_to_bin_blacklist(card_bin)
        return Response({'card_bin': card_bin, 'blacklisted': True})

    def delete(self, request):
        card_bin = request.data.get('card_bin', '').strip()
        if not card_bin:
            return Response({'error': 'card_bin is required.'}, status=400)
        FraudEngine.remove_from_bin_blacklist(card_bin)
        return Response({'card_bin': card_bin, 'blacklisted': False})