"""Проверки пользовательских файлов до сохранения в хранилище."""

from __future__ import annotations

import os
import zipfile

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


def _rewind(uploaded_file):
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass


def validate_uploaded_file(uploaded_file):
    """Проверяет имя, лимит размера и сигнатуру поддерживаемого формата."""
    if not uploaded_file:
        return uploaded_file

    filename = os.path.basename(uploaded_file.name or '')
    if not filename or filename != uploaded_file.name or any(ord(char) < 32 for char in filename):
        raise ValidationError('Недопустимое имя файла.')

    extension = os.path.splitext(filename)[1].lower()
    allowed_extensions = set(settings.ALLOWED_UPLOAD_EXTENSIONS)
    if extension not in allowed_extensions:
        raise ValidationError(
            'Этот тип файла не поддерживается. Разрешены: '
            + ', '.join(sorted(allowed_extensions))
        )

    max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if uploaded_file.size > max_size:
        raise ValidationError(
            f'Файл слишком большой. Максимальный размер — {settings.MAX_UPLOAD_SIZE_MB} МБ.'
        )

    _rewind(uploaded_file)
    header = uploaded_file.read(16)
    _rewind(uploaded_file)
    try:
        if extension == '.pdf' and not header.startswith(b'%PDF-'):
            raise ValidationError('Содержимое файла не соответствует формату PDF.')
        if extension == '.docx':
            if not header.startswith(b'PK'):
                raise ValidationError('Содержимое файла не соответствует формату DOCX.')
            with zipfile.ZipFile(uploaded_file) as archive:
                names = set(archive.namelist())
                if '[Content_Types].xml' not in names or 'word/document.xml' not in names:
                    raise ValidationError('Файл не является корректным документом DOCX.')
                expanded_size = sum(item.file_size for item in archive.infolist())
                if expanded_size > settings.MAX_EXTRACTED_FILE_SIZE_MB * 1024 * 1024:
                    raise ValidationError('DOCX-файл слишком велик после распаковки.')
        elif extension in {'.jpg', '.jpeg', '.png'}:
            try:
                image = Image.open(uploaded_file)
                if image.width * image.height > settings.MAX_IMAGE_PIXELS:
                    raise ValidationError('Разрешение изображения превышает безопасный лимит.')
                image.verify()
                expected = {'JPG': 'JPEG', 'JPEG': 'JPEG', 'PNG': 'PNG'}[extension[1:].upper()]
                if image.format != expected:
                    raise ValidationError('Расширение изображения не соответствует его содержимому.')
            except (UnidentifiedImageError, OSError):
                raise ValidationError('Изображение повреждено или имеет неверный формат.')
        elif extension in {'.txt', '.md', '.csv'}:
            sample = uploaded_file.read(min(uploaded_file.size, 64 * 1024))
            if b'\x00' in sample:
                raise ValidationError('Текстовый файл содержит недопустимые бинарные данные.')
            try:
                sample.decode('utf-8-sig')
            except UnicodeDecodeError:
                try:
                    sample.decode('cp1251')
                except UnicodeDecodeError:
                    raise ValidationError('Не удалось определить кодировку текстового файла.')
    except zipfile.BadZipFile:
        raise ValidationError('DOCX-файл повреждён или имеет неверный формат.')
    finally:
        _rewind(uploaded_file)

    return uploaded_file


def scan_uploaded_file(uploaded_file):
    """Передаёт содержимое в clamd по внутреннему TCP-соединению."""
    if settings.TESTING or not settings.CLAMAV_ENABLED:
        return uploaded_file

    try:
        import clamd

        scanner = clamd.ClamdNetworkSocket(
            host=settings.CLAMAV_HOST,
            port=settings.CLAMAV_PORT,
            timeout=settings.CLAMAV_TIMEOUT,
        )
        scanner.ping()
        _rewind(uploaded_file)
        result = scanner.instream(uploaded_file)
        status, signature = result.get('stream', ('ERROR', 'неизвестный ответ'))
        if status == 'FOUND':
            raise ValidationError(f'Файл отклонён антивирусом: {signature}.')
        if status != 'OK':
            raise RuntimeError(signature or status)
    except ValidationError:
        raise
    except Exception as exc:
        if settings.CLAMAV_FAIL_CLOSED:
            raise ValidationError(
                'Антивирус временно недоступен. Подождите обновления базы ClamAV и повторите загрузку.'
            ) from exc
    finally:
        _rewind(uploaded_file)

    return uploaded_file
