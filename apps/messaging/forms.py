from django import forms

from apps.accounts.models import User
from apps.courses import permissions as perm

from . import services
from .models import Announcement


class ComposeForm(forms.Form):
    recipient = forms.ModelChoiceField(queryset=User.objects.none(), label="To")
    subject = forms.CharField(max_length=150)
    body = forms.CharField(label="Message", max_length=5000, widget=forms.Textarea(attrs={"rows": 6}))

    def __init__(self, *args, sender, **kwargs):
        super().__init__(*args, **kwargs)
        self.sender = sender
        self.fields["recipient"].queryset = services.allowed_recipients(sender).order_by("first_name", "last_name", "username")
        self.fields["recipient"].label_from_instance = lambda u: f"{u.get_full_name() or u.username} ({u.get_role_display()}, {u.username})"


class ReplyForm(forms.Form):
    body = forms.CharField(label="Reply", max_length=5000, widget=forms.Textarea(attrs={"rows": 4}))


class TopicForm(forms.Form):
    title = forms.CharField(max_length=150)
    body = forms.CharField(label="Your post", max_length=5000, widget=forms.Textarea(attrs={"rows": 6}))


class PostForm(forms.Form):
    body = forms.CharField(label="Your reply", max_length=5000, widget=forms.Textarea(attrs={"rows": 4}))


class AnnouncementForm(forms.ModelForm):
    def clean_priority(self):
        return self.cleaned_data.get("priority") or "normal"

    field_order = ["title", "body", "course", "priority", "pinned"]
    course = forms.ModelChoiceField(queryset=None, required=False, empty_label=None, label="Audience")

    class Meta:
        model = Announcement
        fields = ["course", "title", "body", "priority", "pinned"]
        labels = {"body": "Message", "pinned": "Pin to top"}
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["priority"].required = False
        self.fields["course"].queryset = perm.visible_courses_for(user)
        if user.role == "admin":
            self.fields["course"].empty_label = "Whole site (everyone)"
        else:
            self.fields["course"].required = True
