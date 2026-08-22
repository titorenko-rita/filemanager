import logging
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated

from core.telegram_utils import send_telegram_message
from ml_api.models import MLResult
from ml_api.tasks import process_file_task

from .audit import record_action
from .forms import EmailForm, FileReplaceForm, FileUploadForm
from .models import AuditLog, StoredFile
from .serializers import FileSerializer

logger = logging.getLogger(__name__)


def send_file_notification(file_instance, action):
    """Опциональное мета-уведомление; в приватном режиме документ не покидает сервер."""
    if not settings.AUTOMATIC_EMAIL_NOTIFICATIONS or not settings.EMAIL_CONFIGURED:
        return False

    filename = os.path.basename(file_instance.file.name)
    email = EmailMessage(
        f'Файл {action}: {filename}',
        f'Файл {filename} был {action}.\nОписание: {file_instance.description}',
        settings.DEFAULT_FROM_EMAIL,
        [settings.FILE_NOTIFICATION_EMAIL],
    )
    try:
        if (
            settings.AUTOMATIC_EMAIL_ATTACHMENTS
            and not settings.PRIVACY_MODE
            and file_instance.file
            and os.path.exists(file_instance.file.path)
        ):
            email.attach_file(file_instance.file.path)
        email.send(fail_silently=False)
        return True
    except Exception as exc:
        logger.warning('Не удалось отправить автоматическое email-уведомление: %s', type(exc).__name__)
        return False


def enqueue_ml_processing(file_id, queue='high_priority'):
    """Постановка в очередь не должна ломать основную файловую операцию."""
    if settings.TESTING:
        return None
    try:
        return process_file_task.apply_async(args=[file_id], queue=queue)
    except Exception as exc:
        logger.warning('Не удалось поставить файл %s в очередь ML: %s', file_id, exc)
        return None


def _owned_active_file(request, file_id):
    return get_object_or_404(
        StoredFile,
        id=file_id,
        user=request.user,
        is_deleted=False,
    )


@login_required
def upload_file(request):
    if request.method == 'POST':
        form = FileUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file_instance = form.save(commit=False)
            file_instance.user = request.user
            file_instance.save()
            record_action(request, AuditLog.Action.UPLOAD, file_instance)
            send_file_notification(file_instance, 'создан')
            send_telegram_message('📥 В FileManager загружен новый файл.')
            enqueue_ml_processing(file_instance.id)
            messages.success(request, 'Файл загружен и поставлен в очередь локального анализа.')
            return redirect('file_list')
        logger.info('Загрузка отклонена валидатором для пользователя %s.', request.user.username)
    else:
        form = FileUploadForm()
    return render(request, 'core/upload.html', {'form': form})


@login_required
def file_list(request):
    files = StoredFile.objects.filter(user=request.user, is_deleted=False).order_by('-uploaded_at')
    return render(request, 'core/list.html', {'files': files})


@login_required
def download_file(request, file_id):
    file_instance = _owned_active_file(request, file_id)
    file_instance.file.open('rb')
    record_action(request, AuditLog.Action.DOWNLOAD, file_instance)
    return FileResponse(
        file_instance.file,
        as_attachment=True,
        filename=os.path.basename(file_instance.file.name),
    )


@login_required
def replace_file(request, file_id):
    file_instance = _owned_active_file(request, file_id)
    if request.method == 'POST':
        form = FileReplaceForm(request.POST, request.FILES, instance=file_instance)
        if form.is_valid():
            old_file_name = file_instance.file.name if file_instance.file else ''
            old_storage = file_instance.file.storage if file_instance.file else None
            file_instance = form.save()
            if old_file_name and old_file_name != file_instance.file.name and old_storage:
                try:
                    old_storage.delete(old_file_name)
                except Exception:
                    logger.exception('Не удалось удалить предыдущую версию %s.', old_file_name)
            record_action(
                request,
                AuditLog.Action.REPLACE,
                file_instance,
                metadata={'previous_name': os.path.basename(old_file_name)},
            )
            send_file_notification(file_instance, 'заменён')
            send_telegram_message('♻️ В FileManager заменён файл.')
            enqueue_ml_processing(file_instance.id)
            messages.success(request, 'Файл заменён и повторно отправлен на локальный анализ.')
            return redirect('file_list')
    else:
        form = FileReplaceForm(instance=file_instance)
    return render(request, 'core/replace.html', {'form': form, 'file_instance': file_instance})


@login_required
def send_report(request):
    if request.method == 'POST':
        form = EmailForm(request.POST, user=request.user)
        if form.is_valid():
            to_email = form.cleaned_data['to_email']
            selected_file = form.cleaned_data['selected_file']
            try:
                email = EmailMessage(
                    form.cleaned_data['subject'],
                    form.cleaned_data['message'],
                    settings.DEFAULT_FROM_EMAIL,
                    [to_email],
                )
                if selected_file and os.path.exists(selected_file.file.path):
                    email.attach_file(selected_file.file.path)
                if email.send(fail_silently=False) != 1:
                    raise RuntimeError('SMTP-сервер не подтвердил отправку письма')
                record_action(
                    request,
                    AuditLog.Action.EMAIL,
                    selected_file,
                    metadata={'recipient': to_email, 'with_attachment': bool(selected_file)},
                )
                messages.success(request, f'Отчёт отправлен на {to_email}.')
                return redirect('file_list')
            except Exception as exc:
                logger.warning('Ошибка явной SMTP-отправки: %s', type(exc).__name__)
                form.add_error(
                    None,
                    'Не удалось отправить письмо через SMTP. Проверьте подключение, '
                    'SMTP-настройки и пароль для внешнего приложения.',
                )
    else:
        form = EmailForm(user=request.user)
    return render(request, 'core/email_form.html', {'form': form})


@login_required
@require_POST
def delete_file(request, file_id):
    file_instance = _owned_active_file(request, file_id)
    file_instance.move_to_trash(request.user)
    record_action(request, AuditLog.Action.TRASH, file_instance)
    messages.success(request, 'Файл перемещён в корзину. Его можно восстановить.')
    return redirect('file_list')


@login_required
def trash(request):
    files = StoredFile.objects.filter(user=request.user, is_deleted=True).order_by('-deleted_at')
    return render(request, 'core/trash.html', {'files': files})


@login_required
@require_POST
def restore_file(request, file_id):
    file_instance = get_object_or_404(
        StoredFile,
        id=file_id,
        user=request.user,
        is_deleted=True,
    )
    file_instance.restore()
    record_action(request, AuditLog.Action.RESTORE, file_instance)
    messages.success(request, 'Файл восстановлен.')
    return redirect('trash')


@login_required
@require_POST
def purge_file(request, file_id):
    file_instance = get_object_or_404(
        StoredFile,
        id=file_id,
        user=request.user,
        is_deleted=True,
    )
    file_name = file_instance.file.name if file_instance.file else ''
    storage = file_instance.file.storage if file_instance.file else None
    record_action(request, AuditLog.Action.PURGE, file_instance)
    file_instance.delete()
    if file_name and storage:
        try:
            storage.delete(file_name)
        except Exception:
            logger.exception('Не удалось удалить файл %s из хранилища.', file_name)
    messages.success(request, 'Файл окончательно удалён.')
    return redirect('trash')


@login_required
def profile(request):
    files = request.user.files.filter(is_deleted=False)
    recent_files = files.order_by('-uploaded_at')[:5]
    last_file = files.order_by('-uploaded_at').first()
    total_files = files.count()
    return render(request, 'core/profile.html', {
        'user': request.user,
        'user_stats': {
            'total_files': total_files,
            'last_activity': last_file.uploaded_at if last_file else None,
            'recent_files': recent_files,
        },
        'total_files': total_files,
        'last_activity': last_file.uploaded_at if last_file else None,
        'recent_files': recent_files,
    })


@login_required
def status_page(request):
    files = StoredFile.objects.filter(is_deleted=False)
    total_files_size = sum(
        item.file.size
        for item in files
        if item.file and os.path.exists(item.file.path)
    )
    email_status = (
        f'Настроен: {settings.EMAIL_HOST}:{settings.EMAIL_PORT} '
        '(соединение проверяется при явной отправке)'
        if settings.EMAIL_CONFIGURED
        else 'Не настроен или не все данные указаны'
    )
    context = {
        'total_users': User.objects.count(),
        'total_files': files.count(),
        'total_files_size_mb': round(total_files_size / (1024 * 1024), 2),
        'email_status': email_status,
        'privacy_mode': settings.PRIVACY_MODE,
        'clamav_enabled': settings.CLAMAV_ENABLED,
        'telegram_enabled': settings.TELEGRAM_NOTIFICATIONS_ENABLED,
        'automatic_email_enabled': settings.AUTOMATIC_EMAIL_NOTIFICATIONS,
    }
    return render(request, 'core/status.html', context)


@login_required
def audit_log(request):
    if not (request.user.is_staff or request.user.has_perm('core.view_auditlog')):
        raise PermissionDenied
    logs = AuditLog.objects.select_related('actor', 'stored_file').all()[:500]
    return render(request, 'core/audit.html', {'audit_logs': logs})


class FileViewSet(viewsets.ModelViewSet):
    serializer_class = FileSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['description']
    search_fields = ['description']

    def get_queryset(self):
        return StoredFile.objects.filter(user=self.request.user, is_deleted=False)

    def perform_create(self, serializer):
        file_instance = serializer.save(user=self.request.user)
        record_action(self.request, AuditLog.Action.UPLOAD, file_instance)
        send_file_notification(file_instance, 'создан')
        enqueue_ml_processing(file_instance.id)

    def perform_update(self, serializer):
        old_file = self.get_object()
        old_file_name = old_file.file.name if old_file.file else ''
        old_storage = old_file.file.storage if old_file.file else None
        file_instance = serializer.save()
        if old_file_name and old_file_name != file_instance.file.name and old_storage:
            old_storage.delete(old_file_name)
        record_action(
            self.request,
            AuditLog.Action.REPLACE,
            file_instance,
            metadata={'previous_name': os.path.basename(old_file_name)},
        )
        send_file_notification(file_instance, 'заменён')
        enqueue_ml_processing(file_instance.id)

    def perform_destroy(self, instance):
        instance.move_to_trash(self.request.user)
        record_action(self.request, AuditLog.Action.TRASH, instance)


@login_required
def ml_results(request):
    user_files = StoredFile.objects.filter(user=request.user, is_deleted=False)
    results = MLResult.objects.filter(file__in=user_files).order_by('-created_at')
    return render(request, 'core/ml_results.html', {'results': results})


def health_check(request):
    return JsonResponse({'status': 'ok'})
