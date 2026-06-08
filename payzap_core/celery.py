import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'payzap_core.settings')

app = Celery('payzap')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# ── Celery Beat Schedule ──────────────────────────────────────────────────────
app.conf.beat_schedule = {
    'process-daily-settlements': {
        'task': 'settlements.tasks.process_daily_settlements',
        'schedule': crontab(hour=23, minute=0),  # 11 PM daily
    },
    'expire-stale-orders': {
        'task': 'payments.tasks.expire_stale_orders',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
}

app.conf.timezone = 'Asia/Kolkata'