import pytest
from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from tests.factories import MerchantFactory, APIKeyFactory, OrderFactory, PaymentFactory
from fraud.fraud_engine import FraudEngine
from fraud.models import FraudSignal


@pytest.mark.django_db
class TestFraudEngine:

    def setup_method(self):
        self.engine = FraudEngine()

    def test_clean_payment_returns_allow(self):
        result = self.engine.evaluate({
            'card_bin': '411111',
            'ip_address': '192.168.1.1',
            'amount': 50000,
        })
        assert result['action'] == 'allow'
        assert result['total_risk_score'] == 0

    def test_blacklisted_bin_returns_block(self):
        with patch('fraud.fraud_engine._get_redis') as mock_redis:
            r = MagicMock()
            r.sismember.return_value = True
            r.exists.return_value = False
            r.get.return_value = None
            mock_redis.return_value = r

            result = self.engine.evaluate({
                'card_bin': '411111',
                'ip_address': '1.2.3.4',
                'amount': 50000,
            })

        assert result['action'] == 'block'
        assert result['total_risk_score'] >= 80

    def test_card_velocity_exceeded_returns_block(self):
        with patch('fraud.fraud_engine._get_redis') as mock_redis:
            r = MagicMock()
            r.sismember.return_value = False
            r.exists.return_value = False
            r.get.side_effect = lambda key: '5' if 'card_velocity' in key else '0'
            mock_redis.return_value = r

            result = self.engine.evaluate({
                'card_bin': '411111',
                'ip_address': '1.2.3.4',
                'amount': 50000,
            })

        assert result['action'] == 'block'
        assert any(r['rule'] == 'card_velocity' for r in result['triggered_rules'])

    def test_card_already_blocked_returns_block(self):
        with patch('fraud.fraud_engine._get_redis') as mock_redis:
            r = MagicMock()
            r.sismember.return_value = False
            r.exists.return_value = True  # card is hard-blocked
            r.get.return_value = None
            mock_redis.return_value = r

            result = self.engine.evaluate({
                'card_bin': '411111',
                'ip_address': '1.2.3.4',
                'amount': 50000,
            })

        assert result['action'] == 'block'

    def test_ip_velocity_exceeded_returns_flag(self):
        with patch('fraud.fraud_engine._get_redis') as mock_redis:
            r = MagicMock()
            r.sismember.return_value = False
            r.exists.return_value = False
            r.get.side_effect = lambda key: '20' if 'ip_velocity' in key else '0'
            mock_redis.return_value = r

            result = self.engine.evaluate({
                'card_bin': '',
                'ip_address': '1.2.3.4',
                'amount': 50000,
            })

        assert result['action'] == 'flag'
        assert any(r['rule'] == 'ip_velocity' for r in result['triggered_rules'])

    def test_redis_failure_fails_open(self):
        import redis as redis_lib
        with patch('fraud.fraud_engine._get_redis') as mock_redis:
            r = MagicMock()
            r.sismember.side_effect = redis_lib.RedisError('Redis down')
            r.exists.side_effect = redis_lib.RedisError('Redis down')
            r.get.side_effect = redis_lib.RedisError('Redis down')
            mock_redis.return_value = r

            result = self.engine.evaluate({
                'card_bin': '411111',
                'ip_address': '1.2.3.4',
                'amount': 50000,
            })

        # Should fail open — allow the payment
        assert result['action'] == 'allow'

    def test_record_failed_attempt_increments_counters(self):
        with patch('fraud.fraud_engine._get_redis') as mock_redis:
            r = MagicMock()
            mock_redis.return_value = r

            self.engine.record_failed_attempt('411111', '1.2.3.4')

            assert r.incr.call_count == 2
            assert r.expire.call_count == 2

    def test_high_combined_score_returns_block(self):
        with patch('fraud.fraud_engine._get_redis') as mock_redis:
            r = MagicMock()
            r.sismember.return_value = False
            r.exists.return_value = False
            # Both card velocity and IP velocity triggered
            r.get.side_effect = lambda key: (
                '5' if 'card_velocity' in key else
                '20' if 'ip_velocity' in key else '0'
            )
            mock_redis.return_value = r

            result = self.engine.evaluate({
                'card_bin': '411111',
                'ip_address': '1.2.3.4',
                'amount': 50000,
            })

        assert result['action'] == 'block'
        assert result['total_risk_score'] >= 80


@pytest.mark.django_db
class TestFraudSignalRecording:

    def setup_method(self):
        self.engine = FraudEngine()
        self.merchant = MerchantFactory()
        self.order = OrderFactory(merchant=self.merchant)
        self.payment = PaymentFactory(order=self.order, status='created')

    def test_signals_recorded_to_db(self):
        result = {
            'action': 'flag',
            'total_risk_score': 60,
            'triggered_rules': [{
                'rule': 'ip_velocity',
                'risk_score': 60,
                'action': 'flag',
                'details': {'ip_address': '1.2.3.4', 'attempts': 25},
            }],
        }
        self.engine.record_signals(self.payment, result)

        signal = FraudSignal.objects.filter(payment=self.payment).first()
        assert signal is not None
        assert signal.rule_triggered == 'ip_velocity'
        assert signal.risk_score == 60
        assert signal.status == 'pending_review'

    def test_no_signals_recorded_when_clean(self):
        result = {
            'action': 'allow',
            'total_risk_score': 0,
            'triggered_rules': [],
        }
        self.engine.record_signals(self.payment, result)
        assert FraudSignal.objects.filter(payment=self.payment).count() == 0


@pytest.mark.django_db
class TestBINBlacklist:

    def setup_method(self):
        self.client = APIClient()
        self.merchant = MerchantFactory()
        self.api_key = APIKeyFactory(merchant=self.merchant)
        self.client.credentials(HTTP_X_API_KEY=self.api_key.full_key)

    def test_add_bin_to_blacklist(self):
        with patch('fraud.fraud_engine._get_redis') as mock_redis:
            r = MagicMock()
            mock_redis.return_value = r

            resp = self.client.post('/v1/fraud/bin-blacklist/', {
                'card_bin': '411111'
            }, format='json')

        assert resp.status_code == 200
        assert resp.data['blacklisted'] is True

    def test_invalid_bin_returns_400(self):
        resp = self.client.post('/v1/fraud/bin-blacklist/', {
            'card_bin': '123'
        }, format='json')
        assert resp.status_code == 400

    def test_non_digit_bin_returns_400(self):
        resp = self.client.post('/v1/fraud/bin-blacklist/', {
            'card_bin': 'ABCDEF'
        }, format='json')
        assert resp.status_code == 400