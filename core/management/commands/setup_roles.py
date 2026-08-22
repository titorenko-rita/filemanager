from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Создаёт или обновляет системные роли FileManager.'

    def handle(self, *args, **options):
        auditors, _ = Group.objects.get_or_create(name='Аудиторы')
        permission = Permission.objects.get(codename='view_auditlog')
        auditors.permissions.add(permission)
        self.stdout.write(self.style.SUCCESS('Роль «Аудиторы» настроена.'))
