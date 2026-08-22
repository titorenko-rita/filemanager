from django.urls import path, include
from . import views
from .views import ml_results

# Стандартные URL-адреса
urlpatterns = [
    path('upload/', views.upload_file, name='upload_file'),
    path('', views.file_list, name='file_list'),
    path('download/<int:file_id>/', views.download_file, name='download_file'),
    path('replace/<int:file_id>/', views.replace_file, name='replace_file'),
    path('send_report/', views.send_report, name='send_report'),
    path('delete/<int:file_id>/', views.delete_file, name='delete_file'),
    path('trash/', views.trash, name='trash'),
    path('restore/<int:file_id>/', views.restore_file, name='restore_file'),
    path('purge/<int:file_id>/', views.purge_file, name='purge_file'),
    path('audit/', views.audit_log, name='audit_log'),
    path('profile/', views.profile, name='profile'),
    path('status/', views.status_page, name='status'),
    path('api/ml/', include('ml_api.urls')),
    path('ml_results/', ml_results, name='ml_results'),
]
