from django import forms
from .models import StoredFile
from .security import scan_uploaded_file, validate_uploaded_file

class FileUploadForm(forms.ModelForm):
    class Meta:
        model = StoredFile
        fields = ['file', 'description']
        labels = {
            'file': 'Файл',
            'description': 'Описание',
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data['file']
        validate_uploaded_file(uploaded_file)
        scan_uploaded_file(uploaded_file)
        return uploaded_file


class FileReplaceForm(FileUploadForm):
    """A replacement must always contain a new file."""

    file = forms.FileField(label='Новый файл', required=True)

class EmailForm(forms.Form):
    to_email = forms.EmailField(label='Email получателя')
    subject = forms.CharField(label='Тема', max_length=100)
    message = forms.CharField(label='Сообщение', widget=forms.Textarea)
    selected_file = forms.ModelChoiceField(
        label='Выберите файл',
        queryset=StoredFile.objects.none(),
        required=False,
        empty_label='Без прикрепления файла',
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['selected_file'].queryset = StoredFile.objects.filter(
                user=user,
                is_deleted=False,
            )
