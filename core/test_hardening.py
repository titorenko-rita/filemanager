import io
import os
import sys
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from core.management.commands.backup_project import Command as BackupCommand
from core.models import AuditLog, StoredFile
from core.security import scan_uploaded_file, validate_uploaded_file
from core.tasks import create_project_backup, purge_expired_data
from core.views import send_file_notification


@pytest.fixture
def regular_user(db):
    return User.objects.create_user('rita', 'rita@example.com', 'password123')


@pytest.fixture
def logged_client(client, regular_user):
    client.login(username='rita', password='password123')
    return client


def uploaded(name, content=b'test'):
    return SimpleUploadedFile(name, content)


def valid_docx_bytes():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<document/>')
    return stream.getvalue()


def valid_png_bytes(size=(2, 2)):
    stream = io.BytesIO()
    Image.new('RGB', size, 'white').save(stream, format='PNG')
    return stream.getvalue()


def test_upload_validator_accepts_supported_formats(settings):
    settings.MAX_UPLOAD_SIZE_MB = 1
    settings.MAX_EXTRACTED_FILE_SIZE_MB = 1
    settings.MAX_IMAGE_PIXELS = 100
    settings.ALLOWED_UPLOAD_EXTENSIONS = ('.txt', '.pdf', '.docx', '.png')

    assert validate_uploaded_file(uploaded('note.txt', 'Привет'.encode()))
    assert validate_uploaded_file(uploaded('report.pdf', b'%PDF-1.4\n'))
    assert validate_uploaded_file(uploaded('report.docx', valid_docx_bytes()))
    assert validate_uploaded_file(uploaded('image.png', valid_png_bytes()))


@pytest.mark.parametrize(
    ('name', 'content', 'message'),
    [
        ('tool.exe', b'MZ', 'не поддерживается'),
        ('fake.pdf', b'not pdf', 'не соответствует'),
        ('fake.docx', b'not zip', 'не соответствует'),
        ('broken.docx', b'PK broken', 'повреждён'),
        ('binary.txt', b'a\x00b', 'бинарные'),
        ('invalid.txt', b'\x81\x98\x90', 'кодировку'),
        ('fake.png', b'not image', 'повреждено'),
    ],
)
def test_upload_validator_rejects_invalid_files(settings, name, content, message):
    settings.ALLOWED_UPLOAD_EXTENSIONS = ('.txt', '.pdf', '.docx', '.png')
    with pytest.raises(ValidationError, match=message):
        validate_uploaded_file(uploaded(name, content))


def test_upload_validator_rejects_size_and_dimensions(settings):
    settings.ALLOWED_UPLOAD_EXTENSIONS = ('.txt', '.png')
    settings.MAX_UPLOAD_SIZE_MB = 0
    with pytest.raises(ValidationError, match='слишком большой'):
        validate_uploaded_file(uploaded('large.txt', b'x'))

    settings.MAX_UPLOAD_SIZE_MB = 1
    settings.MAX_IMAGE_PIXELS = 1
    with pytest.raises(ValidationError, match='превышает'):
        validate_uploaded_file(uploaded('large.png', valid_png_bytes()))


def test_upload_validator_rejects_unsafe_name(settings):
    settings.ALLOWED_UPLOAD_EXTENSIONS = ('.txt',)
    candidate = Mock(name='../safe.txt', size=4)
    candidate.name = '../safe.txt'
    with pytest.raises(ValidationError, match='имя'):
        validate_uploaded_file(candidate)


def _fake_clamd(result=None, error=None):
    scanner = Mock()
    if error:
        scanner.ping.side_effect = error
    else:
        scanner.instream.return_value = result
    module = Mock()
    module.ClamdNetworkSocket.return_value = scanner
    return module, scanner


def test_clamav_accepts_clean_file(settings):
    settings.TESTING = False
    settings.CLAMAV_ENABLED = True
    module, scanner = _fake_clamd({'stream': ('OK', None)})
    with patch.dict(sys.modules, {'clamd': module}):
        candidate = uploaded('note.txt')
        assert scan_uploaded_file(candidate) is candidate
    scanner.ping.assert_called_once()


def test_clamav_rejects_infected_and_unavailable(settings):
    settings.TESTING = False
    settings.CLAMAV_ENABLED = True
    settings.CLAMAV_FAIL_CLOSED = True
    infected, _ = _fake_clamd({'stream': ('FOUND', 'Eicar-Test-Signature')})
    with patch.dict(sys.modules, {'clamd': infected}):
        with pytest.raises(ValidationError, match='Eicar'):
            scan_uploaded_file(uploaded('note.txt'))

    unavailable, _ = _fake_clamd(error=OSError('offline'))
    with patch.dict(sys.modules, {'clamd': unavailable}):
        with pytest.raises(ValidationError, match='недоступен'):
            scan_uploaded_file(uploaded('note.txt'))

    settings.CLAMAV_FAIL_CLOSED = False
    with patch.dict(sys.modules, {'clamd': unavailable}):
        assert scan_uploaded_file(uploaded('note.txt'))


@pytest.mark.django_db
def test_trash_restore_and_purge(logged_client, regular_user):
    stored_file = StoredFile.objects.create(
        user=regular_user,
        file=uploaded('trash-me.txt', b'data'),
    )
    storage = stored_file.file.storage
    path = stored_file.file.name

    assert logged_client.post(reverse('delete_file', args=[stored_file.id])).status_code == 302
    stored_file.refresh_from_db()
    assert stored_file.is_deleted
    assert logged_client.get(reverse('download_file', args=[stored_file.id])).status_code == 404
    assert logged_client.get(reverse('trash')).status_code == 200

    assert logged_client.post(reverse('restore_file', args=[stored_file.id])).status_code == 302
    stored_file.refresh_from_db()
    assert not stored_file.is_deleted

    logged_client.post(reverse('delete_file', args=[stored_file.id]))
    assert logged_client.post(reverse('purge_file', args=[stored_file.id])).status_code == 302
    assert not StoredFile.objects.filter(id=stored_file.id).exists()
    assert not storage.exists(path)
    assert AuditLog.objects.filter(action=AuditLog.Action.PURGE, file_name='trash-me.txt').exists()


@pytest.mark.django_db
def test_audit_access_is_role_protected(client, regular_user):
    client.login(username='rita', password='password123')
    assert client.get(reverse('audit_log')).status_code == 403
    regular_user.user_permissions.add(Permission.objects.get(codename='view_auditlog'))
    regular_user = User.objects.get(pk=regular_user.pk)
    regular_user.user_permissions.add(Permission.objects.get(codename='view_auditlog'))
    assert client.get(reverse('audit_log')).status_code == 200


@pytest.mark.django_db
def test_api_hides_soft_deleted_files(regular_user):
    stored_file = StoredFile.objects.create(user=regular_user, file=uploaded('hidden.txt'))
    stored_file.move_to_trash(regular_user)
    api = APIClient()
    api.force_authenticate(regular_user)
    response = api.get(reverse('files-list'))
    assert response.status_code == 200
    assert response.data['count'] == 0


@pytest.mark.django_db
def test_models_restore_and_string_values(regular_user):
    stored_file = StoredFile.objects.create(user=regular_user, file=uploaded('model.txt'))
    stored_file.move_to_trash(regular_user)
    stored_file.restore()
    assert not stored_file.is_deleted
    assert 'uploads/model' in str(stored_file)
    event = AuditLog.objects.create(
        actor=regular_user,
        action=AuditLog.Action.UPLOAD,
        stored_file=stored_file,
        file_name='model.txt',
    )
    assert 'model.txt' in str(event)


@pytest.mark.django_db
def test_retention_purges_only_expired_data(settings, regular_user):
    settings.TRASH_RETENTION_DAYS = 30
    settings.AUDIT_RETENTION_DAYS = 365
    old_file = StoredFile.objects.create(user=regular_user, file=uploaded('old.txt'))
    old_file.move_to_trash(regular_user)
    StoredFile.objects.filter(pk=old_file.pk).update(deleted_at=timezone.now() - timedelta(days=31))
    fresh_file = StoredFile.objects.create(user=regular_user, file=uploaded('fresh.txt'))
    fresh_file.move_to_trash(regular_user)
    old_event = AuditLog.objects.create(actor=regular_user, action=AuditLog.Action.LOGIN)
    AuditLog.objects.filter(pk=old_event.pk).update(created_at=timezone.now() - timedelta(days=366))

    result = purge_expired_data()
    assert result['files'] == 1
    assert not StoredFile.objects.filter(pk=old_file.pk).exists()
    assert StoredFile.objects.filter(pk=fresh_file.pk).exists()
    assert result['audit_events'] >= 1


@pytest.mark.django_db
def test_backup_command_creates_archive_without_secrets(settings, tmp_path):
    settings.BACKUP_ROOT = tmp_path / 'backups'
    settings.MEDIA_ROOT = tmp_path / 'media'
    settings.MEDIA_ROOT.mkdir()
    (settings.MEDIA_ROOT / 'document.txt').write_text('document', encoding='utf-8')

    def fake_database_backup(_command, staging):
        target = staging / 'database.dump'
        target.write_bytes(b'database')
        return target

    with patch.object(BackupCommand, '_backup_database', fake_database_backup):
        call_command('backup_project', verbosity=0)

    archive_path = next(settings.BACKUP_ROOT.glob('*.zip'))
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert 'database.dump' in names
        assert 'media/document.txt' in names
        assert '.env' not in names
        assert b'"contains_secrets": false' in archive.read('manifest.json')


def test_backup_database_variants(settings, tmp_path):
    command = BackupCommand()
    sqlite_file = tmp_path / 'source.sqlite3'
    sqlite_file.write_bytes(b'sqlite')
    sqlite_settings = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': sqlite_file}}
    with patch('core.management.commands.backup_project.settings.DATABASES', sqlite_settings):
        assert command._backup_database(tmp_path).read_bytes() == b'sqlite'

    postgres_stage = tmp_path / 'postgres'
    postgres_stage.mkdir()
    postgres_settings = {'default': {
        'ENGINE': 'django.db.backends.postgresql', 'NAME': 'files', 'USER': 'user',
        'PASSWORD': 'secret', 'HOST': 'db', 'PORT': '5432',
    }}
    with patch('core.management.commands.backup_project.settings.DATABASES', postgres_settings), \
            patch('core.management.commands.backup_project.subprocess.run') as run:
            result = command._backup_database(postgres_stage)
    assert result.name == 'database.dump'
    assert run.call_args.kwargs['env']['PGPASSWORD'] == 'secret'

    unsupported_settings = {'default': {'ENGINE': 'unknown', 'NAME': 'files'}}
    with patch('core.management.commands.backup_project.settings.DATABASES', unsupported_settings):
        with pytest.raises(Exception, match='не поддерживается'):
            command._backup_database(tmp_path)


def test_backup_task_and_management_commands(db):
    with patch('core.tasks.call_command') as command:
        assert create_project_backup.run() == {'status': 'ok'}
    command.assert_called_once_with('backup_project')
    call_command('setup_roles', verbosity=0)
    call_command('apply_retention', verbosity=0)


@pytest.mark.django_db
def test_notification_is_metadata_only_when_privacy_disabled(settings, regular_user):
    settings.AUTOMATIC_EMAIL_NOTIFICATIONS = True
    settings.AUTOMATIC_EMAIL_ATTACHMENTS = True
    settings.EMAIL_CONFIGURED = True
    settings.PRIVACY_MODE = True
    stored_file = StoredFile.objects.create(user=regular_user, file=uploaded('private.txt'))
    with patch('core.views.EmailMessage') as email:
        email.return_value.send.return_value = 1
        assert send_file_notification(stored_file, 'создан') is True
        email.return_value.attach_file.assert_not_called()

    with patch('core.views.EmailMessage') as email:
        email.return_value.send.side_effect = OSError('smtp offline')
        assert send_file_notification(stored_file, 'создан') is False
