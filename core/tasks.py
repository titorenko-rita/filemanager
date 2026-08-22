import logging
import os
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from .models import AuditLog, StoredFile

logger = logging.getLogger(__name__)


def purge_expired_data():
    deleted_before = timezone.now() - timedelta(days=settings.TRASH_RETENTION_DAYS)
    audit_before = timezone.now() - timedelta(days=settings.AUDIT_RETENTION_DAYS)
    purged_files = 0

    for stored_file in StoredFile.objects.filter(
        is_deleted=True,
        deleted_at__lt=deleted_before,
    ).iterator():
        file_name = stored_file.file.name if stored_file.file else ''
        storage = stored_file.file.storage if stored_file.file else None
        stored_file.delete()
        if file_name and storage:
            try:
                storage.delete(file_name)
            except Exception:
                logger.exception('Не удалось удалить просроченный файл %s.', file_name)
        purged_files += 1

    purged_audit, _ = AuditLog.objects.filter(created_at__lt=audit_before).delete()
    return {'files': purged_files, 'audit_events': purged_audit}


@shared_task(name='core.tasks.apply_retention_policy')
def apply_retention_policy():
    return purge_expired_data()


@shared_task(name='core.tasks.create_project_backup')
def create_project_backup():
    call_command('backup_project')
    return {'status': 'ok'}
