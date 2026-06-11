import csv
import io
import uuid

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from merchants.authentication import APIKeyAuthentication
from payouts.models import Payout
from payouts.payout_service import create_payout
from payouts.tasks import process_bulk_payout_task, process_payout_task


def _payout_to_dict(p):
    return {
        'id': str(p.id),
        'amount': p.amount,
        'mode': p.mode,
        'purpose': p.purpose,
        'status': p.status,
        'beneficiary_name': p.beneficiary_name,
        'account_number': p.account_number,
        'ifsc': p.ifsc,
        'upi_id': p.upi_id,
        'utr_number': p.utr_number,
        'reference_id': p.reference_id,
        'batch_id': p.batch_id,
        'processed_at': p.processed_at,
        'created_at': p.created_at,
    }


class PayoutCreateView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            payout = create_payout(request.user, request.data)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        process_payout_task.delay(str(payout.id))
        return Response(_payout_to_dict(payout), status=status.HTTP_201_CREATED)


class PayoutBulkView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'CSV file is required.'}, status=400)

        if not file.name.endswith('.csv'):
            return Response({'error': 'Only CSV files are accepted.'}, status=400)

        try:
            content = file.read().decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))
            required_cols = {'beneficiary_name', 'amount'}
            if not required_cols.issubset(set(reader.fieldnames or [])):
                return Response(
                    {'error': f'CSV must contain columns: {required_cols}'},
                    status=400
                )
            rows = list(reader)
        except Exception as e:
            return Response({'error': f'Invalid CSV: {e}'}, status=400)

        if not rows:
            return Response({'error': 'CSV file is empty.'}, status=400)

        if len(rows) > 1000:
            return Response({'error': 'Maximum 1000 rows per batch.'}, status=400)

        # Convert amount to int paise
        try:
            for row in rows:
                row['amount'] = int(row['amount'])
        except ValueError:
            return Response({'error': 'amount must be an integer (paise).'}, status=400)

        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        process_bulk_payout_task.delay(batch_id, str(request.user.id), rows)

        return Response({
            'batch_id': batch_id,
            'queued': len(rows),
            'status': 'processing',
        }, status=status.HTTP_202_ACCEPTED)


class PayoutDetailView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, payout_id):
        try:
            payout = Payout.objects.get(id=payout_id, merchant=request.user)
        except Payout.DoesNotExist:
            return Response({'error': 'Payout not found.'}, status=404)
        return Response(_payout_to_dict(payout))


class PayoutListView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payouts = Payout.objects.filter(merchant=request.user).order_by('-created_at')

        batch_id = request.query_params.get('batch_id')
        payout_status = request.query_params.get('status')
        if batch_id:
            payouts = payouts.filter(batch_id=batch_id)
        if payout_status:
            payouts = payouts.filter(status=payout_status)

        page = int(request.query_params.get('page', 1))
        page_size = 20
        start = (page - 1) * page_size
        end = start + page_size
        total = payouts.count()

        return Response({
            'count': total,
            'page': page,
            'total_pages': (total + page_size - 1) // page_size,
            'items': [_payout_to_dict(p) for p in payouts[start:end]],
        })
