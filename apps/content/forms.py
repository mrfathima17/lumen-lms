from django import forms

from apps.core.uploads import validate_upload

from .models import Resource


class ResourceForm(forms.ModelForm):
    url = forms.URLField(required=False, assume_scheme="https", label="Link address")

    class Meta:
        model = Resource
        fields = ["kind", "title", "topic", "description", "file", "url"]

    def __init__(self, *args, course, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].queryset = course.topics.all()
        self.fields["topic"].empty_label = None
        self.fields["file"].help_text = "Up to 20 MB. PDF, Office files, images, zip, text and code files are accepted."

    def clean(self):
        data = super().clean()
        kind = data.get("kind")
        if kind == Resource.Kind.FILE:
            if not data.get("file"):
                self.add_error("file", "Choose a file to upload.")
            data["url"] = ""
        elif kind == Resource.Kind.LINK:
            if not data.get("url"):
                self.add_error("url", "Enter the link address.")
            data["file"] = None
        return data
