from django import forms
from .models import StoredFile

class FileUploadForm(forms.ModelForm):
    class Meta:
        model = StoredFile
        fields = ['file', 'description']
        labels = {
            'file': 'Файл',
            'description': 'Описание',
        }


class FileReplaceForm(FileUploadForm):
    """A replacement must always contain a new file."""

    file = forms.FileField(label='Новый файл', required=True)

    def clean_file(self):
        if 'file' not in self.files:
            raise forms.ValidationError('Выберите новый файл.')
        return self.cleaned_data['file']


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
            self.fields['selected_file'].queryset = StoredFile.objects.filter(user=user)
