from django.shortcuts import render, get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import MLRequest, MLResult
from core.models import StoredFile
import requests
import mimetypes
from django.http import JsonResponse
from .tasks import process_file_task
from celery.result import AsyncResult
from filemanager.celery import app
from django.contrib.auth.decorators import login_required

# Create your views here.

class MLPredictView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Сохраняем запрос пользователя
        ml_request = MLRequest.objects.create(
            user=request.user,
            input_data=request.data,
            result=None
        )
        return Response({"status": "ok", "request_id": ml_request.id}, status=status.HTTP_201_CREATED)

@login_required
def process_file(request, file_id):
    file = get_object_or_404(StoredFile, id=file_id, user=request.user)
    # Определяем очередь по размеру файла
    if file.file.size < 2 * 1024 * 1024:  # 2 МБ
        task = process_file_task.apply_async(args=[file_id], queue='high_priority')
    else:
        task = process_file_task.apply_async(args=[file_id], queue='low_priority')
    return JsonResponse({'task_id': task.id, 'status': 'processing'})

@login_required
def task_status(request, task_id):
    result = AsyncResult(task_id, app=app)
    return JsonResponse({
        'task_id': task_id,
        'status': result.status,
        'result': result.result if result.successful() else None
    })
