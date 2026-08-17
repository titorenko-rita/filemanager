import logging
import mimetypes
import os

import requests
from celery import shared_task
from django.conf import settings

from core.models import StoredFile
from core.telegram_utils import send_telegram_message
from .models import MLResult

try:
    from docx import Document
except ImportError:  # pragma: no cover
    Document = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


logger = logging.getLogger(__name__)
TEXT_EXTENSIONS = {'.txt', '.csv', '.log', '.md'}


def _extract_docx_text(file_path):
    if Document is None:
        raise RuntimeError('Модуль python-docx не установлен в окружении.')

    document = Document(file_path)
    fragments = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            fragments.extend(cell.text for cell in row.cells)
    return '\n'.join(fragment for fragment in fragments if fragment.strip())


def _extract_pdf_text(file_path):
    if PdfReader is None:
        raise RuntimeError('Модуль pypdf не установлен в окружении.')

    reader = PdfReader(file_path)
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    if not text.strip():
        raise ValueError(
            'PDF не содержит текстового слоя. Для сканированного PDF сначала выполните OCR.'
        )
    return text


def _read_text_file(file_path):
    for encoding in ('utf-8-sig', 'cp1251'):
        try:
            with open(file_path, 'r', encoding=encoding) as source:
                return source.read()
        except UnicodeDecodeError:
            continue
    raise ValueError('Не удалось определить кодировку текстового файла.')


def _service_error(response):
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get('error'):
        return str(body['error'])
    return f'ML-сервис вернул HTTP {response.status_code}'


def _analyze_text(text):
    if not text or not text.strip():
        return {'error': 'В файле не найден текст для анализа.'}

    try:
        response = requests.post(
            f'{settings.ML_SERVICE_URL}/sentiment',
            json={'text': text},
            timeout=120,
        )
        if not response.ok:
            return {'error': _service_error(response)}
        return response.json()
    except requests.RequestException as exc:
        logger.warning('ML-сервис недоступен: %s', type(exc).__name__)
        return {'error': 'ML-сервис временно недоступен. Повторите обработку позже.'}
    except ValueError:
        return {'error': 'ML-сервис вернул некорректный ответ.'}


def _analyze_image(file_path):
    try:
        with open(file_path, 'rb') as source:
            response = requests.post(
                f'{settings.ML_SERVICE_URL}/ocr',
                files={'file': source},
                timeout=120,
            )
        if not response.ok:
            return {'error': _service_error(response)}
        return response.json()
    except requests.RequestException as exc:
        logger.warning('OCR-сервис недоступен: %s', type(exc).__name__)
        return {'error': 'OCR-сервис временно недоступен. Повторите обработку позже.'}
    except ValueError:
        return {'error': 'OCR-сервис вернул некорректный ответ.'}


@shared_task
def process_file_task(file_id):
    try:
        stored_file = StoredFile.objects.get(id=file_id)
        file_path = stored_file.file.path
        mime, _ = mimetypes.guess_type(file_path)
        extension = os.path.splitext(file_path)[1].lower()

        # После замены файла старый ML-результат больше не относится к его содержимому.
        MLResult.objects.filter(file=stored_file).delete()

        try:
            if mime and mime.startswith('image'):
                result = _analyze_image(file_path)
            elif extension == '.docx':
                result = _analyze_text(_extract_docx_text(file_path))
            elif extension == '.pdf':
                result = _analyze_text(_extract_pdf_text(file_path))
            elif extension in TEXT_EXTENSIONS:
                result = _analyze_text(_read_text_file(file_path))
            else:
                result = {'error': f'Неподдерживаемый тип файла: {extension or "без расширения"}'}
        except Exception as exc:
            logger.exception('Не удалось извлечь содержимое файла %s', stored_file.file.name)
            result = {'error': f'Не удалось прочитать файл: {exc}'}

        MLResult.objects.create(file=stored_file, data=result)
        if result.get('error'):
            send_telegram_message(
                f'❌ Ошибка обработки файла <b>{stored_file.file.name}</b>: '
                f'{result["error"]}'
            )
        else:
            send_telegram_message(f'✅ Файл <b>{stored_file.file.name}</b> успешно обработан!')
        return result
    except Exception as exc:
        logger.exception('Фоновая обработка файла %s завершилась с ошибкой', file_id)
        send_telegram_message(f'❌ Ошибка при обработке файла: {exc}')
        raise
