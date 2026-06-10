from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from merchants.authentication import APIKeyAuthentication
from settlements.models import Settlement


class SettlementListView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        settlements = Settlement.objects.filter(
            merchant=request.user
        ).order_by('-created_at')

        page = int(request.query_params.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        total = settlements.count()

        data = []
        for s in settlements[start:end]:
            data.append({
                'id': str(s.id),
                'amount': s.amount,
                'fees': s.fees,
                'status': s.status,
                'utr_number': s.utr_number,
                'settlement_from': s.settlement_from,
                'settlement_to': s.settlement_to,
                'settled_at': s.settled_at,
                'created_at': s.created_at,
            })

        return Response({
            'count': total,
            'page': page,
            'total_pages': (total + page_size - 1) // page_size,
            'items': data,
        })