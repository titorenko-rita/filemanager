from django.urls import path
from .views import MLPredictView, process_file
from .views import task_status
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('predict/', MLPredictView.as_view(), name='ml_predict'),
    path('process/<int:file_id>/', process_file, name='process_file'),
    path('task_status/<str:task_id>/', task_status, name='task_status'),
]

