from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import StoredFile
from ml_api.models import MLResult
from ml_api.tasks import _analyze_text, _extract_pdf_text, process_file_task


def test_analyze_text_returns_service_error_message():
    response = Mock(ok=False, status_code=500)
    response.json.return_value = {'error': 'Текст слишком длинный'}
    with patch('ml_api.tasks.requests.post', return_value=response):
        assert _analyze_text('тест') == {'error': 'Текст слишком длинный'}


def test_analyze_text_sends_json_and_accepts_success():
    response = Mock(ok=True)
    response.json.return_value = {'sentiment': 'neutral'}
    with patch('ml_api.tasks.requests.post', return_value=response) as post:
        assert _analyze_text('пример') == {'sentiment': 'neutral'}
    assert post.call_args.kwargs['json'] == {'text': 'пример'}


@patch('ml_api.tasks.PdfReader')
def test_extract_pdf_text(mock_reader):
    first_page = Mock()
    first_page.extract_text.return_value = 'Первая страница'
    second_page = Mock()
    second_page.extract_text.return_value = 'Вторая страница'
    mock_reader.return_value.pages = [first_page, second_page]

    assert _extract_pdf_text('document.pdf') == 'Первая страница\nВторая страница'


@pytest.mark.django_db
def test_processing_error_replaces_stale_result_and_reports_failure():
    user = User.objects.create_user('ml-user')
    stored_file = StoredFile.objects.create(
        user=user,
        file=SimpleUploadedFile('document.docx', b'not-a-real-docx'),
    )
    MLResult.objects.create(file=stored_file, data={'sentiment': 'stale'})

    with patch('ml_api.tasks._extract_docx_text', side_effect=ValueError('broken')), \
            patch('ml_api.tasks.send_telegram_message') as telegram:
        result = process_file_task.run(stored_file.id)

    assert result['error'].startswith('Не удалось прочитать файл:')
    assert MLResult.objects.filter(file=stored_file).count() == 1
    assert MLResult.objects.get(file=stored_file).data == result
    assert telegram.call_args.args[0].startswith('❌ Ошибка обработки файла')


@pytest.mark.django_db
def test_successful_processing_reports_success():
    user = User.objects.create_user('ml-success-user')
    stored_file = StoredFile.objects.create(
        user=user,
        file=SimpleUploadedFile('note.txt', 'Хороший день'.encode()),
    )

    with patch('ml_api.tasks._analyze_text', return_value={'sentiment': 'positive'}), \
            patch('ml_api.tasks.send_telegram_message') as telegram:
        result = process_file_task.run(stored_file.id)

    assert result == {'sentiment': 'positive'}
    assert telegram.call_args.args[0].startswith('✅ Файл')
