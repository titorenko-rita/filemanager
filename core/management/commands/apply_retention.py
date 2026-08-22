from django.core.management.base import BaseCommand

from core.tasks import purge_expired_data


class Command(BaseCommand):
    help = 'Окончательно удаляет просроченную корзину и старые записи аудита.'

    def handle(self, *args, **options):
        result = purge_expired_data()
        self.stdout.write(
            self.style.SUCCESS(
                f'Удалено файлов: {result["files"]}; записей аудита: {result["audit_events"]}.'
            )
        )
