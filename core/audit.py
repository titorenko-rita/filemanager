"""Единая запись значимых действий пользователей."""

from __future__ import annotations

import os


def get_client_ip(request):
    # Приложение в Docker доступно только через доверенный Nginx.
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR')


def record_action(request, action, stored_file=None, *, file_name='', metadata=None):
    from .models import AuditLog

    actor = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
    if not file_name and stored_file and stored_file.file:
        file_name = os.path.basename(stored_file.file.name)
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        stored_file=stored_file,
        file_name=file_name,
        ip_address=get_client_ip(request),
        metadata=metadata or {},
    )
