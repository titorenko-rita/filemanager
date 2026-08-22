from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# Create your models here.

class StoredFile(models.Model):
    file = models.FileField(upload_to='uploads/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=100, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='files')
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_files',
    )

    def move_to_trash(self, user):
        if not self.is_deleted:
            self.is_deleted = True
            self.deleted_at = timezone.now()
            self.deleted_by = user
            self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        if self.is_deleted:
            self.is_deleted = False
            self.deleted_at = None
            self.deleted_by = None
            self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def __str__(self):
        return f"{self.file.name} ({self.uploaded_at})"


class AuditLog(models.Model):
    class Action(models.TextChoices):
        UPLOAD = 'upload', 'Загрузка'
        DOWNLOAD = 'download', 'Скачивание'
        REPLACE = 'replace', 'Замена'
        TRASH = 'trash', 'Перемещение в корзину'
        RESTORE = 'restore', 'Восстановление'
        PURGE = 'purge', 'Окончательное удаление'
        EMAIL = 'email', 'Отправка по email'
        LOGIN = 'login', 'Вход'

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='file_audit_events',
    )
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    stored_file = models.ForeignKey(
        StoredFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_events',
    )
    file_name = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        username = self.actor.username if self.actor else 'system'
        return f'{self.get_action_display()}: {self.file_name} ({username})'
