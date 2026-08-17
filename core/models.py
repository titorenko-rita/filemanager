from django.db import models
from django.contrib.auth.models import User

# Create your models here.

class StoredFile(models.Model):
    file = models.FileField(upload_to='uploads/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=100, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='files')

    def __str__(self):
        return f"{self.file.name} ({self.uploaded_at})"
