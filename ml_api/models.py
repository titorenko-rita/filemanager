from django.db import models
from django.contrib.auth.models import User
from core.models import StoredFile

# Create your models here.

class MLRequest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    input_data = models.JSONField()
    result = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class MLResult(models.Model):
    file = models.ForeignKey(StoredFile, on_delete=models.CASCADE)
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"MLResult for {self.file.name} at {self.created_at}"
