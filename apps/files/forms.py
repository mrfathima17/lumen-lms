from django import forms

from . import services
from .models import PrivateFile


class UploadForm(forms.ModelForm):
    class Meta:
        model = PrivateFile
        fields = ["file"]

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not services.can_store(self.owner, f.size):
            u = services.usage(self.owner)
            raise forms.ValidationError(f"Not enough space: this file is {services.human(f.size)} and you have {services.human(u['left'])} left. Delete something first.")
        return f

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.owner = self.owner
        obj.size = self.cleaned_data["file"].size
        if commit:
            obj.save()
        return obj
