import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import AuditLog, StoredFile


class Command(BaseCommand):
    help = 'Создаёт локальную ZIP-копию базы и каталога media без файла .env.'

    def handle(self, *args, **options):
        backup_root = Path(settings.BACKUP_ROOT)
        backup_root.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
        final_path = backup_root / f'filemanager-{timestamp}.zip'
        temporary_archive = backup_root / f'.filemanager-{timestamp}.tmp'

        try:
            with tempfile.TemporaryDirectory(prefix='filemanager-backup-') as temp_dir:
                staging = Path(temp_dir)
                database_path = self._backup_database(staging)
                manifest = {
                    'created_at': timezone.now().isoformat(),
                    'database_engine': settings.DATABASES['default']['ENGINE'],
                    'database_file': database_path.name,
                    'stored_files': StoredFile.objects.count(),
                    'audit_events': AuditLog.objects.count(),
                    'contains_secrets': False,
                }
                (staging / 'manifest.json').write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )

                with zipfile.ZipFile(
                    temporary_archive,
                    mode='w',
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as archive:
                    archive.write(database_path, database_path.name)
                    archive.write(staging / 'manifest.json', 'manifest.json')
                    media_root = Path(settings.MEDIA_ROOT)
                    if media_root.exists():
                        for media_file in media_root.rglob('*'):
                            if media_file.is_file():
                                archive.write(media_file, Path('media') / media_file.relative_to(media_root))
            os.replace(temporary_archive, final_path)
            try:
                os.chmod(final_path, 0o600)
            except OSError:
                pass
        except Exception as exc:
            temporary_archive.unlink(missing_ok=True)
            raise CommandError(f'Не удалось создать резервную копию: {exc}') from exc

        self._remove_expired_backups(backup_root)
        self.stdout.write(self.style.SUCCESS(f'Резервная копия создана: {final_path}'))

    def _backup_database(self, staging):
        database = settings.DATABASES['default']
        engine = database['ENGINE']
        if engine.endswith('postgresql'):
            destination = staging / 'database.dump'
            environment = os.environ.copy()
            environment['PGPASSWORD'] = str(database.get('PASSWORD', ''))
            subprocess.run(
                [
                    'pg_dump',
                    '--host', str(database.get('HOST') or 'localhost'),
                    '--port', str(database.get('PORT') or '5432'),
                    '--username', str(database.get('USER') or ''),
                    '--format', 'custom',
                    '--file', str(destination),
                    str(database['NAME']),
                ],
                check=True,
                env=environment,
                capture_output=True,
            )
            return destination

        if engine.endswith('sqlite3'):
            destination = staging / 'database.sqlite3'
            shutil.copy2(database['NAME'], destination)
            return destination

        raise CommandError(f'Резервное копирование СУБД {engine} не поддерживается.')

    def _remove_expired_backups(self, backup_root):
        cutoff = timezone.now() - timedelta(days=settings.BACKUP_RETENTION_DAYS)
        for backup in backup_root.glob('filemanager-*.zip'):
            modified = timezone.datetime.fromtimestamp(
                backup.stat().st_mtime,
                tz=timezone.get_current_timezone(),
            )
            if modified < cutoff:
                backup.unlink()
