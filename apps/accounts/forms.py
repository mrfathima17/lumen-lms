from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm


class SignInForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "That username and password do not match. Check them and try again.",
        "inactive": "This account is disabled. Contact your administrator.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autofocus": True, "placeholder": "e.g. s2026-0142"})
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password", "placeholder": "Password"})


class LumenPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, auto in (("old_password", "current-password"), ("new_password1", "new-password"), ("new_password2", "new-password")):
            self.fields[name].widget.attrs["autocomplete"] = auto


from django import forms  # noqa: E402

from .models import User  # noqa: E402


class OwnProfileForm(forms.ModelForm):
    """What people may change about themselves. Username, role, index number and faculty are set by administrators."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "bio", "date_of_birth", "emergency_contact", "email_notifications"]
        widgets = {"bio": forms.Textarea(attrs={"rows": 3}), "date_of_birth": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        labels = {"date_of_birth": "Date of birth", "emergency_contact": "Emergency contact"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["email"].help_text = "Used for password help and notifications."
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["phone"].widget.attrs["autocomplete"] = "tel"
        self.fields["email_notifications"].label = "Email me my notifications"
