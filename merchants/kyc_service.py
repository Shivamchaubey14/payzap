import boto3
import logging
import uuid
from django.conf import settings
from django.utils import timezone
from merchants.models import Merchant, KYCDocument

logger = logging.getLogger(__name__)

# Documents required before KYC can be submitted
REQUIRED_DOCUMENTS = {'aadhar', 'pan', 'cancelled_cheque'}


class KYCService:

    def get_upload_url(self, merchant: Merchant, document_type: str, file_name: str, mime_type: str) -> dict:
        """
        Generate a presigned S3 PUT URL.
        Merchant uploads directly to S3 — our server never touches the file bytes.
        Returns: {upload_url, file_key, expires_in}
        """
        if document_type not in dict(KYCDocument.DOCUMENT_TYPES):
            raise ValueError(f'Invalid document type: {document_type}')

        # Build a safe S3 key
        ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else 'bin'
        file_key = f"kyc/{merchant.id}/{document_type}/{uuid.uuid4().hex}.{ext}"

        try:
            s3 = self._get_s3_client()
            upload_url = s3.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': file_key,
                    'ContentType': mime_type,
                },
                ExpiresIn=900,  # 15 minutes
            )
        except Exception as e:
            logger.warning(f"S3 presigned URL failed, using mock: {e}")
            # Mock URL for development without S3
            upload_url = f"https://mock-s3.payzap.test/{file_key}?presigned=true"

        # Create or update KYCDocument record
        KYCDocument.objects.update_or_create(
            merchant=merchant,
            document_type=document_type,
            defaults={
                'file_key': file_key,
                'file_name': file_name,
                'mime_type': mime_type,
                'status': 'uploaded',
            }
        )

        return {
            'upload_url': upload_url,
            'file_key': file_key,
            'expires_in': 900,
        }

    def submit_kyc(self, merchant: Merchant) -> dict:
        """
        Merchant submits KYC for review.
        Validates all required documents are uploaded.
        Transitions: pending/rejected → submitted
        """
        if merchant.kyc_status == 'approved':
            raise ValueError('KYC is already approved.')

        if merchant.kyc_status == 'under_review':
            raise ValueError('KYC is already under review.')

        # Check required documents
        uploaded = set(
            KYCDocument.objects.filter(
                merchant=merchant,
                status='uploaded',
            ).values_list('document_type', flat=True)
        )

        missing = REQUIRED_DOCUMENTS - uploaded
        if missing:
            raise ValueError(
                f"Missing required documents: {', '.join(sorted(missing))}"
            )

        # Validate bank details are filled
        if not merchant.bank_account_number or not merchant.bank_ifsc:
            raise ValueError('Bank account number and IFSC are required before submitting KYC.')

        # Transition state
        Merchant.objects.filter(id=merchant.id).update(
            kyc_status='submitted',
            kyc_submitted_at=timezone.now(),
            kyc_rejection_reason='',
        )
        merchant.kyc_status = 'submitted'

        # Send confirmation email async
        try:
            from merchants.kyc_tasks import send_kyc_submitted_email
            send_kyc_submitted_email.delay(str(merchant.id))
        except Exception as e:
            logger.warning(f"KYC email task failed: {e}")

        return {'kyc_status': 'submitted', 'message': 'KYC submitted for review.'}

    def approve_kyc(self, merchant: Merchant, reviewed_by: str) -> dict:
        """
        Admin approves KYC.
        Transitions: submitted/under_review → approved
        Triggers penny drop verification then activates merchant.
        """
        if merchant.kyc_status not in ('submitted', 'under_review'):
            raise ValueError(f'Cannot approve KYC in status: {merchant.kyc_status}')

        now = timezone.now()
        Merchant.objects.filter(id=merchant.id).update(
            kyc_status='approved',
            kyc_reviewed_at=now,
            kyc_reviewed_by=reviewed_by,
        )
        merchant.kyc_status = 'approved'

        # Mark all uploaded docs as verified
        KYCDocument.objects.filter(
            merchant=merchant,
            status='uploaded'
        ).update(status='verified', verified_at=now)

        # Trigger penny drop + merchant activation
        penny_drop_result = self._verify_bank_account(merchant)
        if penny_drop_result['success']:
            Merchant.objects.filter(id=merchant.id).update(
                bank_verified=True,
                is_live=True,
            )
            self._generate_live_key(merchant)

        # Send approval email
        try:
            from merchants.kyc_tasks import send_kyc_approved_email
            send_kyc_approved_email.delay(str(merchant.id))
        except Exception as e:
            logger.warning(f"KYC approval email failed: {e}")

        return {
            'kyc_status': 'approved',
            'bank_verified': penny_drop_result['success'],
            'is_live': penny_drop_result['success'],
        }

    def reject_kyc(self, merchant: Merchant, reason: str, reviewed_by: str) -> dict:
        """
        Admin rejects KYC with mandatory reason.
        Merchant must re-upload documents and resubmit.
        """
        if not reason or not reason.strip():
            raise ValueError('Rejection reason is mandatory.')

        if merchant.kyc_status not in ('submitted', 'under_review'):
            raise ValueError(f'Cannot reject KYC in status: {merchant.kyc_status}')

        Merchant.objects.filter(id=merchant.id).update(
            kyc_status='rejected',
            kyc_rejection_reason=reason.strip(),
            kyc_reviewed_at=timezone.now(),
            kyc_reviewed_by=reviewed_by,
        )
        merchant.kyc_status = 'rejected'

        # Reset all docs to uploaded so merchant re-uploads
        KYCDocument.objects.filter(merchant=merchant).update(status='uploaded')

        # Send rejection email
        try:
            from merchants.kyc_tasks import send_kyc_rejected_email
            send_kyc_rejected_email.delay(str(merchant.id), reason)
        except Exception as e:
            logger.warning(f"KYC rejection email failed: {e}")

        return {
            'kyc_status': 'rejected',
            'reason': reason,
        }

    def get_kyc_status(self, merchant: Merchant) -> dict:
        """Returns full KYC status including uploaded documents."""
        documents = KYCDocument.objects.filter(merchant=merchant)
        docs_data = [{
            'document_type': doc.document_type,
            'status': doc.status,
            'file_name': doc.file_name,
            'uploaded_at': doc.uploaded_at,
        } for doc in documents]

        uploaded_types = {doc.document_type for doc in documents}
        missing = list(REQUIRED_DOCUMENTS - uploaded_types)

        return {
            'kyc_status': merchant.kyc_status,
            'bank_verified': merchant.bank_verified,
            'is_live': merchant.is_live,
            'rejection_reason': merchant.kyc_rejection_reason,
            'submitted_at': merchant.kyc_submitted_at,
            'reviewed_at': merchant.kyc_reviewed_at,
            'documents': docs_data,
            'missing_required': missing,
            'can_submit': (
                merchant.kyc_status in ('pending', 'rejected') and
                not missing and
                bool(merchant.bank_account_number) and
                bool(merchant.bank_ifsc)
            ),
        }

    def _verify_bank_account(self, merchant: Merchant) -> dict:
        """
        Mock penny drop verification.
        In production: call bank API with account number + IFSC,
        send ₹1, verify name matches.
        """
        logger.info(f"Penny drop verification for merchant {merchant.id}")

        # Mock — always succeeds in dev
        return {
            'success': True,
            'account_holder': merchant.business_name,
            'utr': f"PENNY{uuid.uuid4().hex[:10].upper()}",
        }

    def _generate_live_key(self, merchant: Merchant):
        """Generate a live API key when merchant goes live."""
        from merchants.models import APIKey
        full_key, prefix, key_hash = APIKey.generate_key(is_live=True)
        APIKey.objects.create(
            merchant=merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=True,
            permissions={
                'payments': True,
                'refunds': True,
                'webhooks': True,
                'payouts': True,
            },
        )
        logger.info(f"Live API key generated for merchant {merchant.id}")
        return full_key

    def _get_s3_client(self):
        return boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        )