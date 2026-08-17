from django.shortcuts import render, redirect, get_object_or_404
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from django.utils.translation import gettext_lazy as _ # Импортируем функцию перевода
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .forms import FileUploadForm, FileReplaceForm, EmailForm
from .models import StoredFile # Импортируем модель StoredFile
from .serializers import FileSerializer  # (или нужный тебе сериализатор)
from django.http import FileResponse, JsonResponse
from django.views.decorators.http import require_POST

import os # Импортируем модуль os для работы с файлами
import logging # Импортируем модуль логирования
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from core.telegram_utils import send_telegram_message
from ml_api.models import MLResult
from ml_api.tasks import process_file_task

logger = logging.getLogger(__name__) # Получаем экземпляр логгера для текущего модуля

# Create your views here.

def send_file_notification(file_instance, action):
    # Get just the filename from the full path
    filename = os.path.basename(file_instance.file.name)
    subject = f'Файл {action}: {filename}'
    message = f'Файл {file_instance.file.name} был {action}.\nОписание: {file_instance.description}'
    from_email = settings.DEFAULT_FROM_EMAIL
    to_email = settings.FILE_NOTIFICATION_EMAIL
    
    try:
        email = EmailMessage(
            subject,
            message,
            from_email,
            [to_email]
        )
        
        # Проверяем существование файла перед прикреплением
        if file_instance.file and os.path.exists(file_instance.file.path):
            email.attach_file(file_instance.file.path)
        
        email.send()
        logger.info(f"Уведомление о файле '{file_instance.file.name}' ({action}) успешно отправлено.")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления о файле '{file_instance.file.name}' ({action}): {e}")


def enqueue_ml_processing(file_id, queue='high_priority'):
    """Queue ML work without making file operations depend on Redis availability."""
    if settings.TESTING:
        return None
    try:
        return process_file_task.apply_async(args=[file_id], queue=queue)
    except Exception as exc:
        logger.warning("Не удалось поставить файл %s в очередь ML: %s", file_id, exc)
        return None

@login_required
def upload_file(request):
    if request.method == 'POST':
        form = FileUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file_instance = form.save(commit=False)
            file_instance.user = request.user
            file_instance.save()
            # Отправляем уведомление о создании файла
            send_file_notification(file_instance, 'создан')
            logger.info(f"Пользователь {request.user.username} успешно загрузил файл '{file_instance.file.name}'.")
            # Telegram уведомление о загрузке файла
            send_telegram_message(f"📥 Пользователь {request.user.username} загрузил файл: {file_instance.file.name}")
            enqueue_ml_processing(file_instance.id)
            return redirect('file_list')
        else:
            logger.warning(f"Пользователь {request.user.username} пытался загрузить файл с ошибками формы: {form.errors}")
            send_telegram_message(f"❌ Ошибка загрузки файла пользователем {request.user.username}: {form.errors}")
    else:
        form = FileUploadForm()
    return render(request, 'core/upload.html', {'form': form})

@login_required
def file_list(request):
    files = StoredFile.objects.filter(user=request.user) # Получаем все файлы из базы данных
    logger.info(f"Пользователь {request.user.username} просматривает список файлов.")
    return render(request, 'core/list.html', {'files': files})


@login_required
def download_file(request, file_id):
    file_instance = get_object_or_404(StoredFile, id=file_id, user=request.user)
    file_instance.file.open('rb')
    return FileResponse(
        file_instance.file,
        as_attachment=True,
        filename=os.path.basename(file_instance.file.name),
    )

@login_required
def replace_file(request, file_id):
    file_instance = get_object_or_404(StoredFile, id=file_id, user=request.user)
    if request.method == 'POST':
        form = FileReplaceForm(request.POST, request.FILES, instance=file_instance)
        if form.is_valid():
            old_file_name = None
            old_storage = None
            if file_instance.file:
                old_file_name = file_instance.file.name
                old_storage = file_instance.file.storage
            file_instance = form.save()
            if old_file_name and old_file_name != file_instance.file.name:
                try:
                    old_storage.delete(old_file_name)
                    logger.info(f"Старый файл '{old_file_name}' был успешно удален после замены.")
                except Exception as e:
                    logger.error(f"Ошибка удаления старого файла '{old_file_name}' после замены: {e}")
                    send_telegram_message(f"❌ Ошибка удаления старого файла {old_file_name} пользователем {request.user.username}: {e}")
            # Отправляем уведомление о замене файла
            notification_message = f'Файл {old_file_name} был заменен на {file_instance.file.name}.\nОписание: {file_instance.description}'
            try:
                email = EmailMessage(
                    f'Файл заменен: {old_file_name} -> {file_instance.file.name}',
                    notification_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [settings.FILE_NOTIFICATION_EMAIL]
                )
                if file_instance.file and os.path.exists(file_instance.file.path):
                    email.attach_file(file_instance.file.path)
                email.send()
                logger.info(f"Уведомление о замене файла '{old_file_name}' на '{file_instance.file.name}' успешно отправлено.")
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления о замене файла '{old_file_name}' на '{file_instance.file.name}': {e}")
                send_telegram_message(f"❌ Ошибка отправки email о замене файла {old_file_name} пользователем {request.user.username}: {e}")
            logger.info(f"Пользователь {request.user.username} успешно заменил файл '{old_file_name}' на '{file_instance.file.name}'.")
            send_telegram_message(f"♻️ Пользователь {request.user.username} заменил файл: {old_file_name} на {file_instance.file.name}")
            return redirect('file_list')
        else:
            logger.warning(f"Пользователь {request.user.username} пытался заменить файл {file_instance.file.name} с ошибками формы: {form.errors}")
            send_telegram_message(f"❌ Ошибка замены файла пользователем {request.user.username}: {form.errors}")
            return render(request, 'core/replace.html', {'form': form, 'file_instance': file_instance}, status=200)
    else:
        form = FileReplaceForm(instance=file_instance)
    return render(request, 'core/replace.html', {'form': form, 'file_instance': file_instance})

@login_required
def send_report(request):
    if request.method == 'POST':
        form = EmailForm(request.POST, user=request.user)
        if form.is_valid():
            to_email = form.cleaned_data['to_email']
            subject = form.cleaned_data['subject']
            message = form.cleaned_data['message']
            selected_file = form.cleaned_data['selected_file']
            from_email = settings.DEFAULT_FROM_EMAIL

            try:
                email = EmailMessage(
                    subject,
                    message,
                    from_email,
                    [to_email]
                )
                if selected_file and os.path.exists(selected_file.file.path):
                    email.attach_file(selected_file.file.path)
                sent_count = email.send(fail_silently=False)
                if sent_count != 1:
                    raise RuntimeError('SMTP-сервер не подтвердил отправку письма')
                logger.info(f"Отчет на почту {to_email} успешно отправлен пользователем {request.user.username}.")
                messages.success(request, f'Отчёт отправлен на {to_email}.')
                return redirect('file_list')
            except Exception as e:
                logger.error(f"Ошибка отправки отчета на почту {to_email} пользователем {request.user.username}: {e}")
                form.add_error(
                    None,
                    'Не удалось отправить письмо через SMTP. Проверьте подключение, '
                    'SMTP-настройки и пароль для внешнего приложения.',
                )
        else:
            logger.warning(f"Пользователь {request.user.username} пытался отправить отчет с ошибками формы: {form.errors}")
    else:
        form = EmailForm(user=request.user)
    return render(request, 'core/email_form.html', {'form': form})

@login_required
@require_POST
def delete_file(request, file_id):
    file_instance = get_object_or_404(StoredFile, id=file_id, user=request.user)
    file_name = None
    file_storage = None
    file_description = None
    if file_instance.file:
        file_name = file_instance.file.name
        file_storage = file_instance.file.storage
        file_description = file_instance.description
    file_instance.delete()
    if file_name:
        try:
            file_storage.delete(file_name)
            logger.info(f"Файл '{file_name}' был успешно удален с диска.")
        except Exception as e:
            logger.error(f"Ошибка удаления файла '{file_name}' с диска: {e}")
            send_telegram_message(f"❌ Ошибка удаления файла {file_name} пользователем {request.user.username}: {e}")
    try:
        email = EmailMessage(
            f'Файл удален: {file_name}',
            f'Файл {file_name} был удален.\nОписание: {file_description}',
            settings.DEFAULT_FROM_EMAIL,
            [settings.FILE_NOTIFICATION_EMAIL]
        )
        email.send()
        logger.info(f"Уведомление об удалении файла '{file_name}' успешно отправлено.")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления об удалении файла '{file_name}': {e}")
        send_telegram_message(f"❌ Ошибка отправки email об удалении файла {file_name} пользователем {request.user.username}: {e}")
    logger.info(f"Пользователь {request.user.username} успешно удалил файл '{file_name}'.")
    send_telegram_message(f"🗑️ Пользователь {request.user.username} удалил файл: {file_name}")
    return redirect('file_list')

@login_required
def profile(request):
    user = request.user
    files = user.files.all()  # или другой related_name, если используется
    total_files = files.count()
    last_activity = files.order_by('-uploaded_at').first().uploaded_at if files.exists() else None
    recent_files = files.order_by('-uploaded_at')[:5]
    user_stats = {
        'total_files': total_files,
        'last_activity': last_activity,
        'recent_files': recent_files,
    }
    return render(request, 'core/profile.html', {
        'user': user,
        'user_stats': user_stats,
        'total_files': total_files,
        'last_activity': last_activity,
        'recent_files': recent_files,
    })

def status_page(request):
    total_users = User.objects.count()
    total_files = StoredFile.objects.count()
    total_files_size = 0
    for stored_file in StoredFile.objects.all():
        if stored_file.file and os.path.exists(stored_file.file.path):
            total_files_size += stored_file.file.size
    
    total_files_size_mb = round(total_files_size / (1024 * 1024), 2) # Calculate this before logging

    # Наличие настроек не означает доступность удалённого SMTP-сервера.
    email_configured = settings.EMAIL_CONFIGURED
    email_status = (
        f"Настроен: {settings.EMAIL_HOST}:{settings.EMAIL_PORT} "
        "(доступность проверяется при отправке)"
        if email_configured
        else "Не настроен или не все данные указаны"
    )

    context = {
        'total_users': total_users,
        'total_files': total_files,
        'total_files_size_mb': total_files_size_mb, # Use the calculated variable
        'email_status': email_status,
    }
    logger.info(f"Запрошена страница статуса. Пользователей: {total_users}, Общий размер файлов: {total_files_size_mb} MB, Статус Email: {email_status}.")
    return render(request, 'core/status.html', context)

class FileViewSet(viewsets.ModelViewSet):
    queryset = StoredFile.objects.all()
    serializer_class = FileSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['description']
    search_fields = ['description']

    def get_queryset(self):
        logger.info(f"API: Пользователь {self.request.user.username} запрашивает список файлов через API.")
        # Ensure users can only see their own files
        return StoredFile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        file_instance = serializer.save(user=self.request.user)
        send_file_notification(file_instance, 'создан')
        logger.info(f"API: Пользователь {self.request.user.username} успешно загрузил файл '{file_instance.file.name}' через API.")
        send_telegram_message(f"📥 API: Пользователь {self.request.user.username} загрузил файл: {file_instance.file.name}")
        enqueue_ml_processing(file_instance.id)

    def perform_update(self, serializer):
        old_file = self.get_object()
        old_file_name = old_file.file.name
        old_storage = old_file.file.storage
        file_instance = serializer.save()
        if old_file_name and old_file_name != file_instance.file.name:
            old_storage.delete(old_file_name)
        notification_message = f'Файл {old_file_name} был заменен на {file_instance.file.name}.\nОписание: {file_instance.description}'
        try:
            email = EmailMessage(
                f'Файл заменен: {os.path.basename(old_file_name)} -> {os.path.basename(file_instance.file.name)}',
                notification_message,
                settings.DEFAULT_FROM_EMAIL,
                [settings.FILE_NOTIFICATION_EMAIL]
            )
            if file_instance.file and os.path.exists(file_instance.file.path):
                email.attach_file(file_instance.file.path)
            email.send()
            logger.info(f"API: Уведомление о замене файла '{old_file_name}' на '{file_instance.file.name}' успешно отправлено.")
        except Exception as e:
            logger.error(f"API: Ошибка отправки уведомления о замене файла '{old_file_name}' на '{file_instance.file.name}': {e}")
            send_telegram_message(f"❌ API: Ошибка отправки email о замене файла {old_file_name} пользователем {self.request.user.username}: {e}")
        send_telegram_message(f"♻️ API: Пользователь {self.request.user.username} заменил файл: {old_file_name} на {file_instance.file.name}")

    def perform_destroy(self, instance):
        file_name = instance.file.name
        file_storage = instance.file.storage
        file_description = instance.description
        instance.delete()
        if file_name:
            file_storage.delete(file_name)
        try:
            email = EmailMessage(
                f'Файл удален: {os.path.basename(file_name)}',
                f'Файл {file_name} был удален.\nОписание: {file_description}',
                settings.DEFAULT_FROM_EMAIL,
                [settings.FILE_NOTIFICATION_EMAIL]
            )
            email.send()
            logger.info(f"API: Уведомление об удалении файла '{file_name}' успешно отправлено.")
        except Exception as e:
            logger.error(f"API: Ошибка отправки уведомления об удалении файла '{file_name}': {e}")
            send_telegram_message(f"❌ API: Ошибка отправки email об удалении файла {file_name} пользователем {self.request.user.username}: {e}")
        send_telegram_message(f"🗑️ API: Пользователь {self.request.user.username} удалил файл: {file_name}")

@login_required
def ml_results(request):
    # Получаем все MLResult для файлов текущего пользователя
    user_files = StoredFile.objects.filter(user=request.user)
    results = MLResult.objects.filter(file__in=user_files).order_by('-created_at')
    return render(request, 'core/ml_results.html', {'results': results})

def health_check(request):
    return JsonResponse({'status': 'ok'})
