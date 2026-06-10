import uuid
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from merchants.models import Merchant, APIKey, KYCDocument
from merchants.kyc_service import KYCService


class KYCServiceTest(TestCase):

    def setUp(self):
        self.merchant = Merchant.objects.create(
            business_name='KYC Test Corp',
            email='kyc@test.com',
            phone='9000000030',
            bank_account_number='1234567890123',
            bank_ifsc='HDFC0001234',
        )
        self.service = KYCService()

    def _upload_required_docs(self):
        for doc_type in ('aadhar', 'pan', 'cancelled_cheque'):
            KYCDocument.objects.create(
                merchant=self.merchant,
                document_type=doc_type,
                file_key=f'kyc/{self.merchant.id}/{doc_type}/test.pdf',
                file_name=f'{doc_type}.pdf',
                status='uploaded',
            )

    def test_get_upload_url_returns_presigned_url(self):
        result = self.service.get_upload_url(
            self.merchant, 'aadhar', 'aadhar.pdf', 'application/pdf'
        )
        self.assertIn('upload_url', result)
        self.assertIn('file_key', result)
        self.assertIn('expires_in', result)
        self.assertTrue(result['file_key'].startswith(f'kyc/{self.merchant.id}/aadhar/'))

    def test_get_upload_url_creates_kyc_document(self):
        self.service.get_upload_url(
            self.merchant, 'pan', 'pan.pdf', 'application/pdf'
        )
        self.assertTrue(
            KYCDocument.objects.filter(
                merchant=self.merchant,
                document_type='pan'
            ).exists()
        )

    def test_get_upload_url_invalid_type_raises(self):
        with self.assertRaises(ValueError):
            self.service.get_upload_url(
                self.merchant, 'passport', 'passport.pdf', 'application/pdf'
            )

    def test_submit_kyc_missing_docs_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.service.submit_kyc(self.merchant)
        self.assertIn('Missing required documents', str(ctx.exception))

    def test_submit_kyc_missing_bank_details_raises(self):
        self._upload_required_docs()
        self.merchant.bank_account_number = ''
        self.merchant.save()
        with self.assertRaises(ValueError) as ctx:
            self.service.submit_kyc(self.merchant)
        self.assertIn('Bank account', str(ctx.exception))

    def test_submit_kyc_success(self):
        self._upload_required_docs()
        result = self.service.submit_kyc(self.merchant)
        self.assertEqual(result['kyc_status'], 'submitted')
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.kyc_status, 'submitted')
        self.assertIsNotNone(self.merchant.kyc_submitted_at)

    def test_submit_kyc_already_approved_raises(self):
        self.merchant.kyc_status = 'approved'
        self.merchant.save()
        with self.assertRaises(ValueError):
            self.service.submit_kyc(self.merchant)

    def test_approve_kyc_transitions_to_approved(self):
        self._upload_required_docs()
        self.merchant.kyc_status = 'submitted'
        self.merchant.save()
        result = self.service.approve_kyc(self.merchant, reviewed_by='admin')
        self.assertEqual(result['kyc_status'], 'approved')
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.kyc_status, 'approved')
        self.assertTrue(self.merchant.is_live)
        self.assertTrue(self.merchant.bank_verified)

    def test_approve_kyc_generates_live_key(self):
        self._upload_required_docs()
        self.merchant.kyc_status = 'submitted'
        self.merchant.save()
        self.service.approve_kyc(self.merchant, reviewed_by='admin')
        live_key = APIKey.objects.filter(
            merchant=self.merchant, is_live=True
        ).first()
        self.assertIsNotNone(live_key)
        self.assertTrue(live_key.key_prefix.startswith('rzp_live_'))

    def test_approve_kyc_marks_docs_verified(self):
        self._upload_required_docs()
        self.merchant.kyc_status = 'submitted'
        self.merchant.save()
        self.service.approve_kyc(self.merchant, reviewed_by='admin')
        all_verified = KYCDocument.objects.filter(
            merchant=self.merchant
        ).exclude(status='verified').count()
        self.assertEqual(all_verified, 0)

    def test_approve_kyc_wrong_status_raises(self):
        self.merchant.kyc_status = 'pending'
        self.merchant.save()
        with self.assertRaises(ValueError):
            self.service.approve_kyc(self.merchant, reviewed_by='admin')

    def test_reject_kyc_transitions_to_rejected(self):
        self.merchant.kyc_status = 'submitted'
        self.merchant.save()
        result = self.service.reject_kyc(
            self.merchant,
            reason='Documents unclear.',
            reviewed_by='admin'
        )
        self.assertEqual(result['kyc_status'], 'rejected')
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.kyc_status, 'rejected')
        self.assertEqual(self.merchant.kyc_rejection_reason, 'Documents unclear.')

    def test_reject_kyc_empty_reason_raises(self):
        self.merchant.kyc_status = 'submitted'
        self.merchant.save()
        with self.assertRaises(ValueError):
            self.service.reject_kyc(self.merchant, reason='', reviewed_by='admin')

    def test_reject_kyc_wrong_status_raises(self):
        self.merchant.kyc_status = 'pending'
        self.merchant.save()
        with self.assertRaises(ValueError):
            self.service.reject_kyc(
                self.merchant, reason='Bad docs.', reviewed_by='admin'
            )

    def test_get_kyc_status_shows_missing_docs(self):
        result = self.service.get_kyc_status(self.merchant)
        self.assertIn('missing_required', result)
        self.assertEqual(len(result['missing_required']), 3)
        self.assertFalse(result['can_submit'])

    def test_get_kyc_status_can_submit_true_when_ready(self):
        self._upload_required_docs()
        result = self.service.get_kyc_status(self.merchant)
        self.assertEqual(result['missing_required'], [])
        self.assertTrue(result['can_submit'])


class KYCAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'KYC API Corp {unique}',
            email=f'kycapi_{unique}@test.com',
            phone='9000000031',
        )
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'kyc': True},
        )
        self.api_key = full_key

    def test_update_bank_details_returns_200(self):
        response = self.client.post(
            '/v1/kyc/bank/',
            {'account_number': '1234567890123', 'ifsc': 'HDFC0001234'},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('account_number', response.data)
        self.assertIn('****', response.data['account_number'])

    def test_update_bank_invalid_ifsc_returns_400(self):
        response = self.client.post(
            '/v1/kyc/bank/',
            {'account_number': '1234567890', 'ifsc': 'INVALIDIFSC'},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)

    def test_update_bank_short_account_returns_400(self):
        response = self.client.post(
            '/v1/kyc/bank/',
            {'account_number': '123', 'ifsc': 'HDFC0001234'},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)

    def test_get_upload_url_returns_200(self):
        response = self.client.post(
            '/v1/kyc/upload-url/',
            {
                'document_type': 'aadhar',
                'file_name': 'aadhar.pdf',
                'mime_type': 'application/pdf',
            },
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('upload_url', response.data)
        self.assertIn('file_key', response.data)

    def test_get_upload_url_invalid_mime_returns_400(self):
        response = self.client.post(
            '/v1/kyc/upload-url/',
            {
                'document_type': 'aadhar',
                'file_name': 'aadhar.exe',
                'mime_type': 'application/exe',
            },
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)

    def test_get_upload_url_invalid_doc_type_returns_400(self):
        response = self.client.post(
            '/v1/kyc/upload-url/',
            {
                'document_type': 'passport',
                'file_name': 'passport.pdf',
                'mime_type': 'application/pdf',
            },
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)

    def test_kyc_status_returns_200(self):
        response = self.client.get(
            '/v1/kyc/status/',
            **{'HTTP_X_API_KEY': self.api_key}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('kyc_status', response.data)
        self.assertIn('documents', response.data)
        self.assertIn('missing_required', response.data)

    def test_submit_kyc_without_docs_returns_400(self):
        response = self.client.post(
            '/v1/kyc/submit/',
            {},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Missing required documents', response.data['error'])

    def test_unauthenticated_returns_401(self):
        response = self.client.get('/v1/kyc/status/')
        self.assertEqual(response.status_code, 401)


class KYCFullFlowTest(TestCase):
    """End-to-end KYC flow: upload → submit → approve → live."""

    def setUp(self):
        self.client = APIClient()
        unique = uuid.uuid4().hex[:8]
        self.merchant = Merchant.objects.create(
            business_name=f'Full KYC Corp {unique}',
            email=f'fullkyc_{unique}@test.com',
            phone='9000000032',
            bank_account_number='9876543210123',
            bank_ifsc='ICIC0001234',
        )
        full_key, prefix, key_hash = APIKey.generate_key(is_live=False)
        APIKey.objects.create(
            merchant=self.merchant,
            key_prefix=prefix,
            key_hash=key_hash,
            is_live=False,
            permissions={'kyc': True},
        )
        self.api_key = full_key
        self.service = KYCService()

    def test_full_kyc_approve_flow(self):
        # Step 1 — Upload all required docs
        for doc_type in ('aadhar', 'pan', 'cancelled_cheque'):
            response = self.client.post(
                '/v1/kyc/upload-url/',
                {
                    'document_type': doc_type,
                    'file_name': f'{doc_type}.pdf',
                    'mime_type': 'application/pdf',
                },
                format='json',
                HTTP_X_API_KEY=self.api_key
            )
            self.assertEqual(response.status_code, 200)

        # Step 2 — Submit KYC
        response = self.client.post(
            '/v1/kyc/submit/',
            {},
            format='json',
            HTTP_X_API_KEY=self.api_key
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['kyc_status'], 'submitted')

        # Step 3 — Admin approves
        self.merchant.refresh_from_db()
        result = self.service.approve_kyc(self.merchant, reviewed_by='admin_user')
        self.assertEqual(result['kyc_status'], 'approved')

        # Step 4 — Verify merchant is live
        self.merchant.refresh_from_db()
        self.assertTrue(self.merchant.is_live)
        self.assertTrue(self.merchant.bank_verified)

        # Step 5 — Verify live API key was generated
        live_key = APIKey.objects.filter(
            merchant=self.merchant, is_live=True
        ).first()
        self.assertIsNotNone(live_key)

    def test_full_kyc_reject_and_resubmit_flow(self):
        # Upload docs and submit
        for doc_type in ('aadhar', 'pan', 'cancelled_cheque'):
            KYCDocument.objects.create(
                merchant=self.merchant,
                document_type=doc_type,
                file_key=f'kyc/test/{doc_type}.pdf',
                file_name=f'{doc_type}.pdf',
                status='uploaded',
            )

        self.service.submit_kyc(self.merchant)

        # Admin rejects
        self.merchant.refresh_from_db()
        self.service.reject_kyc(
            self.merchant,
            reason='Aadhar image is blurry.',
            reviewed_by='admin'
        )

        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.kyc_status, 'rejected')
        self.assertFalse(self.merchant.is_live)

        # Merchant re-uploads and resubmits
        result = self.service.submit_kyc(self.merchant)
        self.assertEqual(result['kyc_status'], 'submitted')