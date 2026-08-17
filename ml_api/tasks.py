from celery import shared_task
from .models import MLResult
from core.models import StoredFile
import requests
import mimetypes
from core.telegram_utils import send_telegram_message
import os
from django.conf import settings

# Для docx
try:
    from docx import Document
except ImportError:
    Document = None

@shared_task
def process_file_task(file_id):
    try:
        file = StoredFile.objects.get(id=file_id)
        file_path = file.file.path
        mime, _ = mimetypes.guess_type(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        result = None
        # Обработка изображений
        if mime and mime.startswith('image'):
            try:
                with open(file_path, 'rb') as f:
                    response = requests.post(
                        f"{settings.ML_SERVICE_URL}/ocr",
                        files={'file': f},
                        timeout=60,
                    )
                response.raise_for_status()
                result = response.json()
            except Exception as e:
                result = {'error': f'Ошибка при обработке изображения: {str(e)}'}
        # Обработка docx
        elif ext == '.docx':
            if Document is not None:
                try:
                    doc = Document(file_path)
                    text = '\n'.join([p.text for p in doc.paragraphs])
                    response = requests.post(
                        f"{settings.ML_SERVICE_URL}/sentiment",
                        data={'text': text},
                        timeout=60,
                    )
                    response.raise_for_status()
                    try:
                        result = response.json()
                    except Exception:
                        result = {'error': f'Некорректный ответ от ML-сервиса: {response.text}'}
                except Exception as e:
                    result = {'error': f'Ошибка чтения docx: {e}'}
            else:
                result = {'error': 'Модуль python-docx не установлен в окружении.'}
        # Обработка текстовых файлов
        elif ext in ['.txt', '.csv', '.log', '.md']:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                response = requests.post(
                    f"{settings.ML_SERVICE_URL}/sentiment",
                    data={'text': text},
                    timeout=60,
                )
                response.raise_for_status()
                try:
                    result = response.json()
                except Exception:
                    result = {'error': f'Некорректный ответ от ML-сервиса: {response.text}'}
            except UnicodeDecodeError:
                result = {'error': 'Ошибка декодирования файла. Проверьте кодировку или тип файла.'}
        else:
            result = {'error': f'Неподдерживаемый тип файла: {ext}'}
        
        if result:
            MLResult.objects.create(file=file, data=result)
            send_telegram_message(f"✅ Файл <b>{file.file.name}</b> успешно обработан!")
        return result
    except Exception as e:
        send_telegram_message(f"❌ Ошибка при обработке файла: {e}")
        raise
