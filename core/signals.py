from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .audit import record_action
from .models import AuditLog


@receiver(user_logged_in)
def audit_successful_login(sender, request, user, **kwargs):
    record_action(request, AuditLog.Action.LOGIN)
