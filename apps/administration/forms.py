from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "role", "index_number", "faculty"]

    def clean_username(self):
        u = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=u).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return u

    def clean_index_number(self):
        v = (self.cleaned_data.get("index_number") or "").strip() or None
        if v and User.objects.filter(index_number__iexact=v).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("That index number is already used.")
        return v


class CsvUploadForm(forms.Form):
    file = forms.FileField(label="CSV file")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a .csv file.")
        return f


class ImportOptionsForm(forms.Form):
    """The 'Options' card of the bulk user import. A direct post without the page's `opts` marker gets the defaults (all switches on)."""
    default_role = forms.ChoiceField(choices=User.Role.choices, initial="student", label="Default role")
    sample_password = forms.CharField(required=False, label="Default sample password", strip=True,
                                      help_text="Leave empty to give each person a different random password (recommended).")
    send_email = forms.BooleanField(required=False, initial=True, label="Send welcome email to each user")
    force_change = forms.BooleanField(required=False, initial=True, label="Force password change at first login")
    skip_existing = forms.BooleanField(required=False, initial=True, label="Skip rows that already exist")

    def __init__(self, data=None, *args, **kwargs):
        if data is not None and "opts" not in data:
            data = data.copy()
            data.update({"default_role": data.get("default_role") or "student", "send_email": "on", "force_change": "on", "skip_existing": "on"})
        super().__init__(data, *args, **kwargs)

    def clean_sample_password(self):
        from django.contrib.auth.password_validation import validate_password

        pw = self.cleaned_data.get("sample_password", "")
        if pw:
            try:
                validate_password(pw)
            except forms.ValidationError as exc:
                raise forms.ValidationError(" ".join(exc.messages)) from None
        return pw


# ---------------------------------------------------------------- part 2: settings, theme, access, email

import base64  # noqa: E402
import binascii  # noqa: E402
import ipaddress as _ip  # noqa: E402
import re as _re  # noqa: E402

from django.core.files.base import ContentFile  # noqa: E402
from django.forms import modelformset_factory  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.core.models import LOGIN_BACKGROUNDS, AllowedNetwork, SiteSettings  # noqa: E402
from apps.grading.models import GradeBand  # noqa: E402

from . import email_templates  # noqa: E402
from .models import PLACEHOLDERS, EmailTemplate  # noqa: E402

HEX = _re.compile(r"^#[0-9a-fA-F]{6}$")


def _luminance(hex_color):
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a, b):
    """WCAG contrast ratio between two #rrggbb colours."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ["site_name", "support_email", "password_min_length", "password_require_upper", "password_require_number", "password_require_symbol", "late_penalty_percent_per_day", "quiz_review_policy", "attendance_warning_percent",
                  "private_files_quota_mb", "audit_log_retention_months", "two_factor_policy", "maintenance_mode", "maintenance_message"]
        labels = {"late_penalty_percent_per_day": "Late penalty (% per late day)", "attendance_warning_percent": "Attendance warning below (%)",
                  "private_files_quota_mb": "Private files per user (MB)", "two_factor_policy": "Two-factor sign-in (authenticator app)", "audit_log_retention_months": "Keep the audit log for (months)",
                  "maintenance_mode": "Maintenance mode (only administrators can use the site)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password_min_length"].required = False  # left blank, the current value stays

    def _range(self, name, lo, hi):
        v = self.cleaned_data[name]
        if not lo <= v <= hi:
            raise forms.ValidationError(f"Enter a number from {lo} to {hi}.")
        return v

    def clean_password_min_length(self):
        if self.cleaned_data.get("password_min_length") is None:
            return self.instance.password_min_length
        return self._range("password_min_length", 8, 64)

    def clean_late_penalty_percent_per_day(self):
        return self._range("late_penalty_percent_per_day", 0, 100)

    def clean_attendance_warning_percent(self):
        return self._range("attendance_warning_percent", 0, 100)

    def clean_private_files_quota_mb(self):
        return self._range("private_files_quota_mb", 1, 100000)

    def clean_audit_log_retention_months(self):
        return self._range("audit_log_retention_months", 1, 120)

    def clean_site_name(self):
        v = self.cleaned_data["site_name"].strip()
        if not v:
            raise forms.ValidationError("The site needs a name.")
        return v


_DATA_URL = _re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\s]+)$")
_MAGIC = {"image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",), "image/webp": (b"RIFF",)}
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _decode_image(value, max_bytes, label):
    """A data: URL from the browser's canvas -> (bytes, extension). Checks the type, the real file signature and the size."""
    m = _DATA_URL.match(value.strip())
    if not m:
        raise forms.ValidationError(f"The {label} is not a readable PNG, JPEG or WebP image.")
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except (binascii.Error, ValueError):
        raise forms.ValidationError(f"The {label} could not be read.") from None
    ctype = m.group(1)
    if not raw.startswith(_MAGIC[ctype]) or (ctype == "image/webp" and raw[8:12] != b"WEBP"):
        raise forms.ValidationError(f"The {label} is not a real image file.")
    if len(raw) > max_bytes:
        raise forms.ValidationError(f"The {label} is too large (limit {max_bytes // 1024} KB).")
    return raw, _EXT[ctype]


class ThemeForm(forms.ModelForm):
    # Images are shrunk in the browser (canvas) and sent as data: URLs in these hidden fields; save() stores them as files.
    logo_data = forms.CharField(required=False, widget=forms.HiddenInput)
    login_bg_data = forms.CharField(required=False, widget=forms.HiddenInput)
    remove_logo = forms.BooleanField(required=False, widget=forms.HiddenInput)
    remove_login_image = forms.BooleanField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = SiteSettings
        fields = ["site_name", "brand_color", "brand_color2", "sidebar_color", "font", "radius", "login_bg", "default_mode", "allow_dark_mode"]
        labels = {"site_name": "Site name", "brand_color": "Primary colour", "brand_color2": "Secondary (gradient) colour", "sidebar_color": "Sidebar colour",
                  "font": "Font", "radius": "Corner roundness", "login_bg": "Login background", "default_mode": "Default for new users",
                  "allow_dark_mode": "Let users switch to dark mode"}

    def clean_site_name(self):
        v = self.cleaned_data["site_name"].strip()
        if not v:
            raise forms.ValidationError("The site needs a name.")
        return v

    def _readable_on_white(self, name, what):
        v = (self.cleaned_data.get(name) or "").lower()
        if not HEX.match(v):
            raise forms.ValidationError("Choose a colour.")
        if contrast(v, "#ffffff") < 4.5:
            raise forms.ValidationError(f"This colour is too light: white text on {what} would be hard to read. Choose a darker one.")
        return v

    def clean_brand_color(self):
        return self._readable_on_white("brand_color", "it")

    def clean_brand_color2(self):
        return self._readable_on_white("brand_color2", "the gradient")

    def clean_sidebar_color(self):
        v = self.cleaned_data["sidebar_color"].lower()
        if not HEX.match(v):
            raise forms.ValidationError("Choose a colour.")
        if contrast(v, "#d3d7ee") < 4.5:
            raise forms.ValidationError("This colour is too light for the sidebar's light text. Choose a darker one.")
        return v

    def clean_radius(self):
        v = self.cleaned_data["radius"]
        if not 4 <= v <= 24:
            raise forms.ValidationError("Enter a number from 4 to 24.")
        return v

    def clean_login_bg(self):
        v = (self.cleaned_data.get("login_bg") or "").strip()
        if v and v not in LOGIN_BACKGROUNDS:
            if not HEX.match(v):
                raise forms.ValidationError("Choose one of the backgrounds or a plain colour.")
            if contrast(v.lower(), "#ffffff") < 4.5:
                raise forms.ValidationError("This colour is too light: the white text on the sign-in page would be hard to read.")
            v = v.lower()
        return v

    def clean_logo_data(self):
        v = self.cleaned_data.get("logo_data") or ""
        self._logo = _decode_image(v, 300 * 1024, "logo") if v else None
        return ""

    def clean_login_bg_data(self):
        v = self.cleaned_data.get("login_bg_data") or ""
        self._bg = _decode_image(v, 3 * 1024 * 1024, "background image") if v else None
        return ""

    def save(self, commit=True):
        obj = super().save(commit=False)
        logo, bg = getattr(self, "_logo", None), getattr(self, "_bg", None)
        if logo or self.cleaned_data.get("remove_logo"):
            obj.clear_image("logo")
        if logo:
            obj.logo.save(f"logo.{logo[1]}", ContentFile(logo[0]), save=False)
        if bg or self.cleaned_data.get("remove_login_image"):
            obj.clear_image("login_bg_image")
        if bg:
            obj.login_bg_image.save(f"login.{bg[1]}", ContentFile(bg[0]), save=False)
            obj.login_bg = ""  # the image wins over a preset or colour
        elif obj.login_bg:
            obj.clear_image("login_bg_image")  # picking a preset or colour replaces the image
        if commit:
            obj.save()
        return obj


class BackupSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ["backup_auto", "backup_time", "backup_keep_days"]
        widgets = {"backup_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
                   "backup_keep_days": forms.NumberInput(attrs={"min": 1, "max": 3650})}
        labels = {"backup_auto": "Automatic daily backup", "backup_time": "Backup time", "backup_keep_days": "Keep backups for (days)"}

    def clean_backup_keep_days(self):
        v = self.cleaned_data["backup_keep_days"]
        if not 1 <= v <= 3650:
            raise forms.ValidationError("Enter a number from 1 to 3650.")
        return v


class MaintenanceForm(forms.ModelForm):
    maintenance_at = forms.DateTimeField(required=False, label="Scheduled for", input_formats=["%Y-%m-%dT%H:%M"],
                                         widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))

    class Meta:
        model = SiteSettings
        fields = ["maintenance_mode", "maintenance_message", "maintenance_at"]
        widgets = {"maintenance_message": forms.Textarea(attrs={"rows": 4, "maxlength": 300})}
        labels = {"maintenance_mode": "Enable maintenance mode", "maintenance_message": "Message to users"}

    def clean_maintenance_at(self):
        v = self.cleaned_data.get("maintenance_at")
        if v and v <= timezone.now():
            raise forms.ValidationError("Choose a time in the future.")
        return v

    def clean(self):
        data = super().clean()
        if data.get("maintenance_mode") and data.get("maintenance_at"):
            data["maintenance_at"] = None  # already on: a start time would mean nothing
        return data


class RuleForm(forms.ModelForm):
    class Meta:
        model = AllowedNetwork
        fields = ["name", "cidr", "scope"]

    def clean_cidr(self):
        v = self.cleaned_data["cidr"].strip()
        try:
            net = _ip.ip_network(v, strict=False)
        except ValueError as exc:
            raise forms.ValidationError("Enter a valid IPv4 or IPv6 network, for example 10.20.0.0/16 or 203.0.113.7/32.") from exc
        if net.prefixlen == 0:
            raise forms.ValidationError("A /0 network allows everyone, so it is not a restriction. Remove the rule instead.")
        return v


class GradeBandForm(forms.ModelForm):
    class Meta:
        model = GradeBand
        fields = ["min_percent", "letter", "points"]

    def clean_min_percent(self):
        v = self.cleaned_data["min_percent"]
        if not 0 <= v <= 100:
            raise forms.ValidationError("From 0 to 100.")
        return v

    def clean_points(self):
        v = self.cleaned_data["points"]
        if not 0 <= v <= 9.99:
            raise forms.ValidationError("From 0 to 9.99.")
        return v

    def clean_letter(self):
        v = self.cleaned_data["letter"].strip()
        if not v:
            raise forms.ValidationError("Required.")
        return v


class BaseGradeBandFormSet(forms.BaseModelFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [f.cleaned_data for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not kept:
            raise forms.ValidationError("The grade scale needs at least one row.")
        if not any(r["min_percent"] == 0 for r in kept):
            raise forms.ValidationError("The lowest row must start at 0%, otherwise some marks would have no grade.")


GradeBandFormSet = modelformset_factory(GradeBand, form=GradeBandForm, formset=BaseGradeBandFormSet, extra=2, can_delete=True)


class EmailTemplateForm(forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = ["subject", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 12})}

    def _check(self, name):
        v = self.cleaned_data[name]
        bad = email_templates.unknown_placeholders(v)
        if bad:
            raise forms.ValidationError("Unknown placeholder: " + ", ".join("{" + b + "}" for b in bad) + ". Allowed: " + ", ".join("{" + p + "}" for p in PLACEHOLDERS) + ".")
        return v

    def clean_subject(self):
        return self._check("subject")

    def clean_body(self):
        v = self._check("body")
        if "{password}" not in v and self.instance.key in ("welcome", "password_reset"):
            raise forms.ValidationError("The email must include {password}, otherwise the person cannot sign in.")
        return v


# ---------------------------------------------------------------- part 2c

from apps.accounts.models import ProfileField  # noqa: E402
from apps.courses.models import Course  # noqa: E402


class ProfileFieldForm(forms.ModelForm):
    class Meta:
        model = ProfileField
        fields = ["label", "key", "kind", "choices", "applies_to", "required", "position", "is_active"]
        widgets = {"choices": forms.Textarea(attrs={"rows": 4})}

    def clean_key(self):
        key = self.cleaned_data["key"].lower()
        reserved = {"username", "first_name", "last_name", "email", "role", "index_number", "faculty", "active", "courses"}
        if key in reserved:
            raise forms.ValidationError("That name is already used by a built-in column.")
        return key

    def clean(self):
        data = super().clean()
        if data.get("kind") == "choice":
            opts = [o.strip() for o in (data.get("choices") or "").splitlines() if o.strip()]
            if len(opts) < 2:
                self.add_error("choices", "Give at least two options, one per line.")
            elif len(set(o.lower() for o in opts)) != len(opts):
                self.add_error("choices", "Options must be different from each other.")
        return data


class BulkEnrolForm(forms.Form):
    ROLES = [("student", "Student"), ("lecturer", "Lecturer")]
    course = forms.ModelChoiceField(Course.objects.order_by("code"), label="Course", empty_label=None)
    role = forms.ChoiceField(choices=ROLES, label="Role in course", initial="student")
    cohort = forms.ChoiceField(required=False, label="By cohort")
    identifiers = forms.CharField(required=False, label="Or paste usernames / emails (one per line)",
                                  widget=forms.Textarea(attrs={"rows": 6, "placeholder": "s2026-0142\ns2026-0188"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.courses.services import cohorts

        self.cohort_counts = cohorts()
        self.fields["cohort"].choices = [("", "None")] + [(y, f"Batch {y} ({n})") for y, n in self.cohort_counts]

    def clean_identifiers(self):
        from apps.courses.services import parse_identifiers

        ids = parse_identifiers(self.cleaned_data.get("identifiers", ""))
        if len(ids) > 1000:
            raise forms.ValidationError("That is more than 1000. Split it into smaller batches.")
        return ids

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        if data.get("cohort") and data.get("role") != "student":
            self.add_error("cohort", "Cohorts are groups of students. Choose the Student role, or paste lecturers below.")
        elif not data.get("cohort") and not data.get("identifiers"):
            self.add_error("identifiers", "Choose a cohort or paste at least one username or email.")
        return data
