import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

# Risk score thresholds
BLOCK_THRESHOLD = 80
REVIEW_THRESHOLD = 50

# Velocity rule config
CARD_VELOCITY_LIMIT = 5       # failed attempts
CARD_VELOCITY_WINDOW = 600    # 10 minutes in seconds
CARD_BLOCK_TTL = 3600         # block for 1 hour

IP_VELOCITY_LIMIT = 20        # attempts
IP_VELOCITY_WINDOW = 300      # 5 minutes in seconds


def _get_redis():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


class FraudEngine:
    """
    Evaluates fraud rules against a payment attempt.
    Returns (action, total_risk_score, triggered_rules).
    action: 'allow' | 'block' | 'flag' | 'step_up'
    """

    def evaluate(self, payment_data: dict) -> dict:
        """
        payment_data keys:
          - card_bin: first 6 digits of card
          - ip_address: customer IP
          - payment_id: str UUID
          - amount: int paise
          - merchant_id: str UUID
          - method: card/upi/netbanking/wallet
        """
        triggered = []
        total_score = 0

        # Run all checks
        checks = [
            self._check_bin_blacklist,
            self._check_card_velocity,
            self._check_ip_velocity,
        ]

        for check in checks:
            result = check(payment_data)
            if result:
                triggered.append(result)
                total_score += result['risk_score']

        # Determine final action
        if total_score >= BLOCK_THRESHOLD:
            action = 'block'
        elif total_score >= REVIEW_THRESHOLD:
            action = 'flag'
        elif any(r['action'] == 'block' for r in triggered):
            action = 'block'
        elif any(r['action'] == 'step_up' for r in triggered):
            action = 'step_up'
        elif triggered:
            action = 'flag'
        else:
            action = 'allow'

        return {
            'action': action,
            'total_risk_score': total_score,
            'triggered_rules': triggered,
        }

    def _check_bin_blacklist(self, data: dict) -> dict | None:
        card_bin = data.get('card_bin', '')
        if not card_bin:
            return None

        try:
            r = _get_redis()
            is_blacklisted = r.sismember('fraud:bin_blacklist', card_bin)
            if is_blacklisted:
                return {
                    'rule': 'bin_blacklist',
                    'risk_score': 100,
                    'action': 'block',
                    'details': {'card_bin': card_bin},
                }
        except redis.RedisError as e:
            logger.warning(f'Redis error in BIN blacklist check: {e}')

        return None

    def _check_card_velocity(self, data: dict) -> dict | None:
        card_bin = data.get('card_bin', '')
        if not card_bin:
            return None

        try:
            r = _get_redis()

            # Check if card is already hard-blocked
            block_key = f'fraud:card_blocked:{card_bin}'
            if r.exists(block_key):
                return {
                    'rule': 'card_velocity_blocked',
                    'risk_score': 100,
                    'action': 'block',
                    'details': {
                        'card_bin': card_bin,
                        'reason': 'Card temporarily blocked due to velocity',
                    },
                }

            # Check velocity counter
            velocity_key = f'fraud:card_velocity:{card_bin}'
            count = r.get(velocity_key)
            count = int(count) if count else 0

            if count >= CARD_VELOCITY_LIMIT:
                # Block the card for 1 hour
                r.setex(block_key, CARD_BLOCK_TTL, '1')
                return {
                    'rule': 'card_velocity',
                    'risk_score': 90,
                    'action': 'block',
                    'details': {
                        'card_bin': card_bin,
                        'failed_attempts': count,
                        'window_seconds': CARD_VELOCITY_WINDOW,
                    },
                }
        except redis.RedisError as e:
            logger.warning(f'Redis error in card velocity check: {e}')

        return None

    def _check_ip_velocity(self, data: dict) -> dict | None:
        ip = data.get('ip_address', '')
        if not ip:
            return None

        try:
            r = _get_redis()
            velocity_key = f'fraud:ip_velocity:{ip}'
            count = r.get(velocity_key)
            count = int(count) if count else 0

            if count >= IP_VELOCITY_LIMIT:
                return {
                    'rule': 'ip_velocity',
                    'risk_score': 60,
                    'action': 'flag',
                    'details': {
                        'ip_address': ip,
                        'attempts': count,
                        'window_seconds': IP_VELOCITY_WINDOW,
                    },
                }
        except redis.RedisError as e:
            logger.warning(f'Redis error in IP velocity check: {e}')

        return None

    def record_failed_attempt(self, card_bin: str, ip_address: str):
        """Call this after every failed payment to increment velocity counters."""
        try:
            r = _get_redis()

            if card_bin:
                key = f'fraud:card_velocity:{card_bin}'
                r.incr(key)
                r.expire(key, CARD_VELOCITY_WINDOW)

            if ip_address:
                key = f'fraud:ip_velocity:{ip_address}'
                r.incr(key)
                r.expire(key, IP_VELOCITY_WINDOW)

        except redis.RedisError as e:
            logger.warning(f'Redis error recording failed attempt: {e}')

    def record_signals(self, payment, result: dict):
        """Persist triggered fraud signals to DB for admin review."""
        from fraud.models import FraudRule, FraudSignal

        for triggered in result['triggered_rules']:
            rule = FraudRule.objects.filter(
                rule_name=triggered['rule']
            ).first()

            FraudSignal.objects.create(
                payment=payment,
                rule=rule,
                rule_triggered=triggered['rule'],
                risk_score=triggered['risk_score'],
                action_taken=triggered['action'],
                details=triggered.get('details', {}),
            )

    @staticmethod
    def add_to_bin_blacklist(card_bin: str):
        r = _get_redis()
        r.sadd('fraud:bin_blacklist', card_bin)

    @staticmethod
    def remove_from_bin_blacklist(card_bin: str):
        r = _get_redis()
        r.srem('fraud:bin_blacklist', card_bin)

    @staticmethod
    def is_bin_blacklisted(card_bin: str) -> bool:
        r = _get_redis()
        return bool(r.sismember('fraud:bin_blacklist', card_bin))
