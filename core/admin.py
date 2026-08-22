from django.contrib import admin

from .models import AuditLog, StoredFile


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ('file', 'user', 'uploaded_at', 'is_deleted', 'deleted_at')
    list_filter = ('is_deleted', 'uploaded_at')
    search_fields = ('file', 'description', 'user__username')
    readonly_fields = ('uploaded_at', 'deleted_at', 'deleted_by')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'file_name', 'ip_address')
    list_filter = ('action', 'created_at')
    search_fields = ('actor__username', 'file_name', 'ip_address')
    readonly_fields = (
        'created_at', 'actor', 'action', 'stored_file', 'file_name', 'ip_address', 'metadata'
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

# Register your models here.
