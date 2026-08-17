from django.contrib import admin
from .models import MLResult

@admin.register(MLResult)
class MLResultAdmin(admin.ModelAdmin):
    list_display = ('id', 'file', 'created_at')
    search_fields = ('file__file',)
    list_filter = ('created_at',)
