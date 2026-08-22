from rest_framework import serializers
from .models import StoredFile
from .security import scan_uploaded_file, validate_uploaded_file

class FileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(use_url=False)
    download_url = serializers.SerializerMethodField()

    def get_download_url(self, obj):
        request = self.context.get('request')
        url = f'/download/{obj.pk}/'
        return request.build_absolute_uri(url) if request else url

    def validate_file(self, uploaded_file):
        validate_uploaded_file(uploaded_file)
        scan_uploaded_file(uploaded_file)
        return uploaded_file

    class Meta:
        model = StoredFile
        fields = ('id', 'file', 'download_url', 'description', 'uploaded_at', 'user')
        read_only_fields = ('user',)
