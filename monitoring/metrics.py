from prometheus_client import Counter, Gauge, Histogram

# Payment metrics
payment_created_total = Counter(
    'payzap_payment_created_total',
    'Total payments created',
    ['method', 'merchant_id']
)

payment_captured_total = Counter(
    'payzap_payment_captured_total',
    'Total payments captured',
    ['method', 'merchant_id']
)

payment_failed_total = Counter(
    'payzap_payment_failed_total',
    'Total payments failed',
    ['method', 'failure_reason']
)

payment_processing_duration = Histogram(
    'payzap_payment_processing_seconds',
    'Payment processing duration in seconds',
    ['method'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
)

# Webhook metrics
webhook_delivered_total = Counter(
    'payzap_webhook_delivered_total',
    'Total webhooks delivered successfully',
)

webhook_failed_total = Counter(
    'payzap_webhook_failed_total',
    'Total webhook delivery failures',
)

webhook_dead_letter_total = Counter(
    'payzap_webhook_dead_letter_total',
    'Total webhooks moved to dead letter queue',
)

# Fraud metrics
fraud_blocked_total = Counter(
    'payzap_fraud_blocked_total',
    'Total payments blocked by fraud engine',
    ['rule']
)

fraud_flagged_total = Counter(
    'payzap_fraud_flagged_total',
    'Total payments flagged for review',
    ['rule']
)

# Settlement metrics
settlement_processed_total = Counter(
    'payzap_settlement_processed_total',
    'Total settlements processed',
)

settlement_amount_total = Counter(
    'payzap_settlement_amount_paise_total',
    'Total settlement amount in paise',
)

# Active merchants gauge
active_merchants_total = Gauge(
    'payzap_active_merchants_total',
    'Total active merchants',
)

# API metrics
api_request_duration = Histogram(
    'payzap_api_request_duration_seconds',
    'API request duration',
    ['method', 'endpoint', 'status_code'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)
