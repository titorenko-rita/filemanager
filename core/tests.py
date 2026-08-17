import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.core import mail
from unittest.mock import patch
import os
from core.models import StoredFile
from rest_framework.test import APIClient
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser('testadmin', 'testadmin@example.com', 'password123')


@pytest.fixture
def authenticated_client(client, admin_user):
    client.login(username='testadmin', password='password123')
    # The client instance itself does not have a .user attribute directly from login
    # but request.user will be set in views. We can explicitly set it for clarity if needed in client-side test assertions
    return client


@pytest.fixture
def api_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def test_file(tmp_path):
    file_content = b"This is a test file content."
    file_path = tmp_path / "test_file.txt"
    file_path.write_bytes(file_content)
    return file_path


# --- Tests for File Upload (Web View) ---

def test_file_upload_authenticated(authenticated_client, test_file, mailoutbox, admin_user):
    initial_file_count = StoredFile.objects.count()
    with open(test_file, 'rb') as f:
        response = authenticated_client.post(reverse('upload_file'), {'file': f, 'description': 'A test description'})

    assert response.status_code == 302  # Should redirect on successful upload
    assert StoredFile.objects.count() == initial_file_count + 1
    assert StoredFile.objects.last().description == 'A test description'
    assert StoredFile.objects.last().user.pk == admin_user.pk  # Corrected assertion to use admin_user.pk
    assert len(mailoutbox) == 1
    assert "Файл создан: test_file" in mailoutbox[0].subject
    assert mailoutbox[0].subject.endswith(".txt")

def test_file_upload_anonymous(client, test_file, db):
    initial_file_count = StoredFile.objects.count()
    with open(test_file, 'rb') as f:
        response = client.post(reverse('upload_file'), {'file': f, 'description': 'Another test description'})

    assert response.status_code == 302  # Should redirect to login
    assert "/accounts/login/" in response.url  # Check for login redirect
    assert StoredFile.objects.count() == initial_file_count  # No file should be created


# --- Tests for API Endpoints ---

def test_api_file_list_authenticated(api_client, db):
    response = api_client.get(reverse('files-list'))
    assert response.status_code == 200
    assert 'results' in response.data


def test_api_file_upload_authenticated(api_client, test_file, mailoutbox, db, admin_user):
    # Force authenticate the admin user
    api_client.force_authenticate(user=admin_user)
    
    initial_file_count = StoredFile.objects.count()
    with open(test_file, 'rb') as f:
        response = api_client.post(reverse('files-list'), {'file': f, 'description': 'API test description'},
                                   format='multipart')

    assert response.status_code == 201  # Created
    assert StoredFile.objects.count() == initial_file_count + 1
    assert StoredFile.objects.last().description == 'API test description'
    assert StoredFile.objects.last().user == admin_user
    assert len(mailoutbox) == 1
    assert "Файл создан: test_file" in mailoutbox[0].subject
    assert mailoutbox[0].subject.endswith(".txt")


def test_api_file_list_anonymous(client, db):
    response = client.get(reverse('files-list'))
    assert response.status_code == 403  # Forbidden (unauthenticated users can't access API)


def test_api_file_detail_authenticated(api_client, test_file, db):
    # First upload a file to get its ID
    with open(test_file, 'rb') as f:
        upload_response = api_client.post(reverse('files-list'), {'file': f, 'description': 'Detail test'},
                                          format='multipart')
    file_id = upload_response.data['id']

    response = api_client.get(reverse('files-detail', args=[file_id]))
    assert response.status_code == 200
    assert response.data['description'] == 'Detail test'


def test_api_file_update_authenticated(api_client, test_file, mailoutbox, db, admin_user):
    # Force authenticate the admin user
    api_client.force_authenticate(user=admin_user)
    
    # Upload a file to update
    with open(test_file, 'rb') as f:
        upload_response = api_client.post(reverse('files-list'), {'file': f, 'description': 'Old description'},
                                          format='multipart')
    file_id = upload_response.data['id']
    mailoutbox.clear()  # Clear mailoutbox after initial upload notification

    updated_file_content = b"Updated test file content."
    updated_file_path = test_file.parent / "updated_test_file.txt"
    updated_file_path.write_bytes(updated_file_content)

    with open(updated_file_path, 'rb') as f:
        response = api_client.put(reverse('files-detail', args=[file_id]),
                                  {'file': f, 'description': 'New description'}, format='multipart')

    assert response.status_code == 200  # OK
    assert StoredFile.objects.get(id=file_id).description == 'New description'
    assert len(mailoutbox) == 1
    assert "Файл заменен:" in mailoutbox[0].subject


def test_api_file_delete_authenticated(api_client, test_file, mailoutbox, db, admin_user):
    # Force authenticate the admin user
    api_client.force_authenticate(user=admin_user)
    
    # Upload a file to delete
    with open(test_file, 'rb') as f:
        upload_response = api_client.post(reverse('files-list'), {'file': f, 'description': 'Delete test'},
                                          format='multipart')
    file_id = upload_response.data['id']
    file_name_to_delete = upload_response.data['file'].split('/')[-1]
    mailoutbox.clear()  # Clear mailoutbox after initial upload notification

    response = api_client.delete(reverse('files-detail', args=[file_id]))

    assert response.status_code == 204  # No Content
    assert not StoredFile.objects.filter(id=file_id).exists()
    assert len(mailoutbox) == 1
    assert "Файл удален:" in mailoutbox[0].subject


# --- Tests for Email Sending (Mocking SMTP) ---

@patch('core.views.EmailMessage')
@patch('os.path.exists', return_value=True)
def test_send_file_notification_mocked(mock_os_path_exists, mock_email_message, db, admin_user):
    from core.views import send_file_notification

    # Create a dummy StoredFile instance with SimpleUploadedFile
    dummy_file = SimpleUploadedFile("dummy.txt", b"dummy content")
    stored_file = StoredFile.objects.create(file=dummy_file, description='Dummy file', user=admin_user)

    send_file_notification(stored_file, 'создан')

    mock_email_message.assert_called_once()  # Check if EmailMessage was called
    args, kwargs = mock_email_message.call_args
    assert "Файл создан: dummy" in args[0]  # Check for the base filename
    assert args[0].endswith(".txt")  # Check for the extension
    assert args[3] == [smtp-user@example.com']  # To email
    mock_email_message.return_value.send.assert_called_once()  # Check if send() was called
    mock_email_message.return_value.attach_file.assert_called_once()  # Check if attach_file was called


@patch('core.views.EmailMessage')
@patch('os.path.exists', return_value=True)
def test_send_report_mocked(mock_os_path_exists, mock_email_message, authenticated_client, db, admin_user):
    # Create a dummy StoredFile instance for selection
    dummy_report_file = SimpleUploadedFile("report_dummy.txt", b"report dummy content")
    stored_file = StoredFile.objects.create(file=dummy_report_file, description='Report test', user=admin_user)
    mock_email_message.return_value.send.return_value = 1

    response = authenticated_client.post(reverse('send_report'), data={
        'to_email': 'test@example.com',
        'subject': 'Test Report',
        'message': 'This is a test report.',
        'selected_file': stored_file.id,
    })

    assert response.status_code == 302  # Should redirect
    mock_email_message.assert_called_once()
    args, kwargs = mock_email_message.call_args
    assert args[0] == 'Test Report'
    assert args[3] == ['test@example.com']
    mock_email_message.return_value.send.assert_called_once()
    mock_email_message.return_value.attach_file.assert_called_once()


# --- Tests for Profile and Status Pages ---

def test_profile_page_authenticated(authenticated_client, admin_user):
    # Create some files for the user
    for i in range(3):
        dummy_file = SimpleUploadedFile(f"test_file_{i}.txt", b"test content")
        StoredFile.objects.create(
            file=dummy_file,
            description=f'Test file {i}',
            user=admin_user
        )

    response = authenticated_client.get(reverse('profile'))
    assert response.status_code == 200
    assert 'user_stats' in response.context
    assert response.context['user_stats']['total_files'] == 3
    assert len(response.context['user_stats']['recent_files']) == 3

def test_profile_page_anonymous(client):
    response = client.get(reverse('profile'))
    assert response.status_code == 302  # Should redirect to login
    assert "/accounts/login/" in response.url

def test_status_page_authenticated(authenticated_client, admin_user):
    # Create some files and users for testing
    User.objects.create_user('testuser1', 'test1@example.com', 'password123')
    User.objects.create_user('testuser2', 'test2@example.com', 'password123')
    
    # Create files for different users
    for user in User.objects.all():
        dummy_file = SimpleUploadedFile(f"test_file_{user.username}.txt", b"test content")
        StoredFile.objects.create(
            file=dummy_file,
            description=f'Test file for {user.username}',
            user=user
        )

    response = authenticated_client.get(reverse('status'))
    assert response.status_code == 200
    assert 'total_users' in response.context
    assert 'total_files_size_mb' in response.context
    assert 'email_status' in response.context
    assert response.context['total_users'] == 3  # admin_user + 2 new users

@pytest.mark.django_db
def test_status_page_anonymous(client):
    response = client.get(reverse('status'))
    assert response.status_code == 200
    assert 'total_users' in response.context
    assert 'total_files' in response.context

# --- Tests for Error Handling ---

def test_file_upload_invalid_form(authenticated_client, test_file):
    initial_file_count = StoredFile.objects.count()
    # Try to upload without required fields
    response = authenticated_client.post(reverse('upload_file'), {})
    assert response.status_code == 200  # Should return to form
    assert StoredFile.objects.count() == initial_file_count  # No new file should be created

def test_replace_file_invalid_form(authenticated_client, admin_user):
    # Create a file first
    dummy_file = SimpleUploadedFile("test_file.txt", b"test content")
    stored_file = StoredFile.objects.create(
        file=dummy_file,
        description='Test file',
        user=admin_user
    )

    # Try to replace with invalid form
    response = authenticated_client.post(
        reverse('replace_file', args=[stored_file.id]),
        {}  # Empty form data
    )
    assert response.status_code == 200  # Should return to form
    assert StoredFile.objects.get(id=stored_file.id).description == 'Test file'  # Description should not change

def test_send_report_invalid_form(authenticated_client):
    response = authenticated_client.post(reverse('send_report'), {})
    assert response.status_code == 200  # Should return to form
    assert len(mail.outbox) == 0  # No email should be sent

def test_file_not_found(authenticated_client):
    # Try to access non-existent file
    response = authenticated_client.get(reverse('replace_file', args=[99999]))
    assert response.status_code == 404

    response = authenticated_client.post(reverse('delete_file', args=[99999]))
    assert response.status_code == 404

# --- Tests for Email Error Handling ---

@patch('core.views.EmailMessage')
def test_email_send_failure(mock_email_message, authenticated_client, test_file):
    # Configure mock to raise an exception
    mock_email_message.return_value.send.side_effect = Exception("SMTP error")
    
    # Try to upload a file
    with open(test_file, 'rb') as f:
        response = authenticated_client.post(
            reverse('upload_file'),
            {'file': f, 'description': 'Test description'}
        )
    
    assert response.status_code == 302  # Upload should still succeed
    assert StoredFile.objects.count() == 1  # File should be saved
    mock_email_message.return_value.send.assert_called_once()  # Email attempt should be made

@patch('core.views.EmailMessage')
def test_report_email_send_failure(mock_email_message, authenticated_client, admin_user):
    # Create a file for the report
    dummy_file = SimpleUploadedFile("report.txt", b"report content")
    stored_file = StoredFile.objects.create(
        file=dummy_file,
        description='Test report',
        user=admin_user
    )

    # Configure mock to raise an exception
    mock_email_message.return_value.send.side_effect = Exception("SMTP error")
    
    # Try to send report
    response = authenticated_client.post(
        reverse('send_report'),
        {
            'to_email': 'test@example.com',
            'subject': 'Test Report',
            'message': 'Test message',
            'selected_file': stored_file.id
        }
    )

    assert response.status_code == 200  # Should return to form on error
    assert 'Не удалось отправить письмо через SMTP' in response.content.decode()
    mock_email_message.return_value.send.assert_called_once()  # Email attempt should be made


class SimpleTest(TestCase):
    def test_status(self):
        response = self.client.get("/")
        self.assertIn(response.status_code, [200, 302, 403])
