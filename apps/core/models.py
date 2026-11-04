import datetime
import ipaddress
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .uploads import upload_path

# Login-page background presets (CSS gradients). Only these, a plain #rrggbb colour, or an uploaded image are ever stored,
# so nothing an administrator types can end up as raw CSS.
LOGIN_BACKGROUNDS = [
    "linear-gradient(135deg,#312e81,#7c3aed 60%,#db2777)",
    "linear-gradient(135deg,#7c2d12,#ea580c 55%,#facc15)",
    "linear-gradient(135deg,#064e3b,#059669 60%,#a3e635)",
    "linear-gradient(135deg,#0c4a6e,#0284c7 60%,#67e8f9)",
    "linear-gradient(135deg,#0f172a,#334155 60%,#64748b)",
    "linear-gradient(135deg,#831843,#e11d48 60%,#fb923c)",
]
# name, primary, secondary (gradient), sidebar. All pass the same contrast checks the form enforces.
COLOUR_PRESETS = [
    ("Indigo", "#4f46e5", "#7c3aed", "#14172b"),
    ("Emerald", "#047857", "#0f766e", "#0f2a24"),
    ("Rose", "#e11d48", "#be185d", "#2a1219"),
    ("Ocean", "#0369a1", "#0e7490", "#0c2233"),
    ("Amber", "#b45309", "#c2410c", "#2a1f0c"),
    ("Slate", "#334155", "#475569", "#0f172a"),
]
FONT_CHOICES = [("system", "System default"), ("Inter", "Inter"), ("Poppins", "Poppins"), ("Nunito", "Nunito"),
                ("Roboto", "Roboto"), ("Merriweather", "Merriweather")]


class SiteSettings(models.Model):
    """Single row of system-wide settings, editable by admins. Defaults are the agreed project defaults."""

    class QuizReview(models.TextChoices):
        IMMEDIATE = "immediate", "Right after submitting"
        AFTER_CLOSE = "after_close", "After the quiz closes"
        MANUAL = "manual", "When the lecturer releases it"

    site_name = models.CharField(max_length=80, default="Lumen")
    late_penalty_percent_per_day = models.PositiveSmallIntegerField(default=10)
    quiz_review_policy = models.CharField(max_length=20, choices=QuizReview.choices, default=QuizReview.AFTER_CLOSE)
    attendance_warning_percent = models.PositiveSmallIntegerField(default=80)
    private_files_quota_mb = models.PositiveIntegerField(default=500)
    audit_log_retention_months = models.PositiveSmallIntegerField(default=12)
    support_email = models.EmailField("Support email", blank=True)
    # Password policy, enforced whenever anyone sets or changes a password (apps/core/validators.py)
    password_min_length = models.PositiveSmallIntegerField("Minimum length", default=10)
    password_require_upper = models.BooleanField("Require an uppercase letter", default=False)
    password_require_number = models.BooleanField("Require a number", default=False)
    password_require_symbol = models.BooleanField("Require a symbol", default=False)
    maintenance_mode = models.BooleanField(default=False)
    maintenance_message = models.CharField(max_length=300, blank=True, default="Lumen is being updated. Please try again shortly.")
    maintenance_at = models.DateTimeField("scheduled for", null=True, blank=True)  # maintenance mode switches on by itself at this time
    # Automatic backups (run by the scheduler; see apps/administration/backups.py run_scheduled)
    backup_auto = models.BooleanField(default=True)
    backup_time = models.TimeField(default=datetime.time(2, 0))
    backup_keep_days = models.PositiveSmallIntegerField(default=30)
    last_auto_backup = models.DateTimeField(null=True, blank=True, editable=False)
    # Branding, applied on every page for everyone (dark mode itself is still each person's own choice).
    brand_color = models.CharField(max_length=7, default="#4f46e5")
    sidebar_color = models.CharField(max_length=7, default="#171a2e")
    brand_color2 = models.CharField("secondary colour", max_length=7, default="#7c3aed")  # second stop of the brand gradient
    font = models.CharField(max_length=20, choices=FONT_CHOICES, default="system")
    radius = models.PositiveSmallIntegerField("corner roundness (px)", default=12)
    login_bg = models.CharField(max_length=120, blank=True, default="")  # "", one of LOGIN_BACKGROUNDS, or #rrggbb
    logo = models.FileField(upload_to=upload_path("branding"), blank=True)  # shrunk to 128 px by the browser, re-checked on save
    login_bg_image = models.FileField(upload_to=upload_path("branding"), blank=True)

    class DefaultMode(models.TextChoices):
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"
        SYSTEM = "system", "Follow the device"

    default_mode = models.CharField(max_length=10, choices=DefaultMode.choices, default=DefaultMode.LIGHT)
    allow_dark_mode = models.BooleanField(default=True)

    class TwoFactorPolicy(models.TextChoices):
        OFF = "off", "Optional for everyone"
        ADMINS = "admins", "Required for administrators"
        STAFF = "staff", "Required for administrators and lecturers"
        EVERYONE = "everyone", "Required for everyone"

    two_factor_policy = models.CharField(max_length=10, choices=TwoFactorPolicy.choices, default=TwoFactorPolicy.OFF)

    class Meta:
        verbose_name = "site settings"
        verbose_name_plural = "site settings"

    def __str__(self):
        return "Site settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    BRANDING_FIELDS = ("site_name", "brand_color", "brand_color2", "sidebar_color", "font", "radius", "login_bg", "default_mode", "allow_dark_mode")

    def apply_schedule(self):
        """Switch maintenance mode on when its scheduled time has come. True when it did. Needs no background worker:
        the maintenance middleware calls this on every request."""
        if not self.maintenance_at or self.maintenance_at > timezone.now():
            return False
        n = SiteSettings.objects.filter(pk=self.pk, maintenance_at__lte=timezone.now()).update(maintenance_mode=True, maintenance_at=None)
        if n:
            self.maintenance_mode, self.maintenance_at = True, None
        return bool(n)

    @property
    def maintenance_upcoming(self):
        """Scheduled within the next two days: users get a heads-up banner."""
        now = timezone.now()
        return bool(self.maintenance_at and not self.maintenance_mode and now < self.maintenance_at <= now + datetime.timedelta(days=2))

    def reset_branding(self):
        """Back to the Lumen look: defaults for every branding field and the uploaded images removed."""
        d = SiteSettings()
        for f in self.BRANDING_FIELDS:
            setattr(self, f, getattr(d, f))
        self.clear_image("logo")
        self.clear_image("login_bg_image")
        self.save()

    def clear_image(self, name):
        f = getattr(self, name)
        if f:
            f.delete(save=False)
        setattr(self, name, "")

    @property
    def logo_version(self):
        return os.path.basename(self.logo.name)[:12] if self.logo else ""

    @property
    def login_bg_css(self):
        """Value for the --login-bg CSS variable ('' means use the default hero colour)."""
        if self.login_bg_image:
            return f"url('/branding/login-bg/?v={os.path.basename(self.login_bg_image.name)[:12]}') center/cover no-repeat"
        return self.login_bg


class AllowedNetwork(models.Model):
    """Network (CIDR) allow-list. If a scope has any active rule, only listed networks may enter it."""

    class Scope(models.TextChoices):
        ALL = "all", "Whole site"
        QUIZ = "quiz", "Quizzes"
        ADMIN = "admin", "Admin area"

    name = models.CharField(max_length=80)
    cidr = models.CharField("Network (CIDR)", max_length=64, help_text="e.g. 10.20.0.0/16 or 203.0.113.7/32")
    scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.QUIZ)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["scope", "name"]

    def __str__(self):
        return f"{self.name} ({self.cidr})"

    def clean(self):
        try:
            ipaddress.ip_network(self.cidr.strip(), strict=False)
        except ValueError as exc:
            raise ValidationError({"cidr": "Enter a valid IPv4 or IPv6 network, for example 10.20.0.0/16."}) from exc

    def save(self, *args, **kwargs):
        self.cidr = self.cidr.strip()
        super().save(*args, **kwargs)


class AuditLog(models.Model):
    class Result(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked by IP rule"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=200, blank=True)
    detail = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    result = models.CharField(max_length=10, choices=Result.choices, default=Result.SUCCESS, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"


class ModuleSetting(models.Model):
    """One row per optional module that has been switched. No row means the module is on."""
    key = models.CharField(max_length=30, unique=True)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key}: {'on' if self.enabled else 'off'}"


class JobHeartbeat(models.Model):
    """The scheduler touches its row every minute, so the admin overview can warn when background jobs have stopped."""
    name = models.CharField(max_length=40, unique=True)
    last_run = models.DateTimeField()

    def __str__(self):
        return f"{self.name} @ {self.last_run:%Y-%m-%d %H:%M}"
