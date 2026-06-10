import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from merchants.authentication import APIKeyAuthentication
from merchants.models import Merchant, KYCDocument
from merchants.kyc_service import KYCService

logger = logging.getLogger(__name__)


class KYCUploadURLView(APIView):
    """
    POST /v1/kyc/upload-url/
    Returns a presigned S3 URL for direct document upload.
    Merchant uploads file directly to S3 — PayZap never handles raw bytes.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        document_type = request.data.get('document_type')
        file_name = request.data.get('file_name')
        mime_type = request.data.get('mime_type', 'application/octet-stream')

        if not document_type:
            return Response({'error': 'document_type is required.'}, status=400)
        if not file_name:
            return Response({'error': 'file_name is required.'}, status=400)

        allowed_types = dict(KYCDocument.DOCUMENT_TYPES).keys()
        if document_type not in allowed_types:
            return Response({
                'error': f'Invalid document_type. Allowed: {", ".join(allowed_types)}'
            }, status=400)

        allowed_mimes = {
            'application/pdf', 'image/jpeg', 'image/png', 'image/jpg'
        }
        if mime_type not in allowed_mimes:
            return Response({
                'error': 'Only PDF, JPEG and PNG files are allowed.'
            }, status=400)

        service = KYCService()
        try:
            result = service.get_upload_url(
                request.user, document_type, file_name, mime_type
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

        return Response(result, status=status.HTTP_200_OK)


class KYCStatusView(APIView):
    """
    GET /v1/kyc/status/
    Returns full KYC status including uploaded documents and missing requirements.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = KYCService()
        return Response(service.get_kyc_status(request.user))


class KYCSubmitView(APIView):
    """
    POST /v1/kyc/submit/
    Merchant submits KYC for admin review.
    Validates all required documents are uploaded.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        service = KYCService()
        try:
            result = service.submit_kyc(request.user)
            return Response(result)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)


class KYCAdminReviewView(APIView):
    """
    POST /v1/kyc/review/
    Admin-only endpoint to approve or reject KYC.
    Requires Django staff authentication (JWT).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Must be Django staff
        if not request.user.is_staff:
            return Response({'error': 'Admin access required.'}, status=403)

        merchant_id = request.data.get('merchant_id')
        action = request.data.get('action')  # 'approve' or 'reject'
        reason = request.data.get('reason', '')

        if not merchant_id or not action:
            return Response(
                {'error': 'merchant_id and action are required.'},
                status=400
            )

        if action not in ('approve', 'reject'):
            return Response(
                {'error': 'action must be approve or reject.'},
                status=400
            )

        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({'error': 'Merchant not found.'}, status=404)

        service = KYCService()
        try:
            if action == 'approve':
                result = service.approve_kyc(merchant, reviewed_by=str(request.user))
            else:
                result = service.reject_kyc(
                    merchant,
                    reason=reason,
                    reviewed_by=str(request.user)
                )
            return Response(result)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)


class KYCUpdateBankView(APIView):
    """
    POST /v1/kyc/bank/
    Update merchant bank account details required for settlement.
    """
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import re
        account_number = request.data.get('account_number', '').strip()
        ifsc = request.data.get('ifsc', '').strip().upper()

        if not account_number:
            return Response({'error': 'account_number is required.'}, status=400)
        if not ifsc:
            return Response({'error': 'ifsc is required.'}, status=400)

        if not re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', ifsc):
            return Response(
                {'error': 'Invalid IFSC format. Example: HDFC0001234'},
                status=400
            )

        if not (9 <= len(account_number) <= 18):
            return Response(
                {'error': 'Account number must be 9-18 digits.'},
                status=400
            )

        Merchant.objects.filter(id=request.user.id).update(
            bank_account_number=account_number,
            bank_ifsc=ifsc,
            bank_verified=False,  # Reset verification on change
        )

        return Response({
            'message': 'Bank details updated.',
            'account_number': f"{'*' * (len(account_number) - 4)}{account_number[-4:]}",
            'ifsc': ifsc,
        })