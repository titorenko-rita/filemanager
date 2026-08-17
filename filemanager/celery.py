import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'filemanager.settings')

app = Celery('filemanager')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

from celery.signals import worker_ready

@worker_ready.connect
def at_start(sender, **kwargs):
    from core.telegram_utils import send_telegram_message
    send_telegram_message("🚀 Celery worker запущен!")