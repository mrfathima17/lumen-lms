from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class LumenUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        LECTURER = "lecturer", "Lecturer"
        ADMIN = "admin", "Administrator"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT, db_index=True)
    index_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    faculty = models.CharField(max_length=100, blank=True)
    batch = models.CharField(max_length=60, blank=True, help_text="Cohort, such as Batch 2026. Set by an administrator.")
    phone = models.CharField(max_length=30, blank=True)
    bio = models.CharField(max_length=500, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    emergency_contact = models.CharField(max_length=80, blank=True)
    # Set when an admin creates the account with a sample password: forces a change at first sign-in.
    must_change_password = models.BooleanField(default=False)
    dashboard_layout = models.JSONField(default=dict, blank=True, help_text="Student dashboard: {\"order\": [...], \"hidden\": [...]}.")
    email_notifications = models.BooleanField(default=True, help_text="Also send me notifications by email (when an email address is set).")

    objects = LumenUserManager()

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        if self.index_number == "":
            self.index_number = None
        super().save(*args, **kwargs)

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_lecturer(self):
        return self.role == self.Role.LECTURER

    @property
    def is_lumen_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def initials(self):
        parts = (self.get_full_name() or self.username).split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    @property
    def home_url_name(self):
        return {"student": "accounts:student-dashboard", "lecturer": "accounts:lecturer-dashboard"}.get(
            self.role, "accounts:admin-overview"
        )


class ProfileField(models.Model):
    """An extra field an administrator adds to user profiles (for example faculty year or hostel)."""

    class Kind(models.TextChoices):
        TEXT = "text", "Short text"
        NUMBER = "number", "Number"
        DATE = "date", "Date"
        CHOICE = "choice", "Choose from a list"

    class AppliesTo(models.TextChoices):
        ALL = "all", "Everyone"
        STUDENT = "student", "Students only"
        LECTURER = "lecturer", "Lecturers only"

    label = models.CharField(max_length=60)
    key = models.SlugField(max_length=40, unique=True, help_text="Short name used in CSV exports, e.g. hostel")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TEXT)
    choices = models.TextField(blank=True, help_text="One option per line (only for 'Choose from a list').")
    applies_to = models.CharField(max_length=10, choices=AppliesTo.choices, default=AppliesTo.ALL)
    required = models.BooleanField(default=False, help_text="Administrators must fill it in when editing a user.")
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.label

    @property
    def options(self):
        return [o.strip() for o in self.choices.splitlines() if o.strip()]

    def applies_to_role(self, role):
        return self.applies_to == "all" or self.applies_to == role


class ProfileValue(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="profile_values")
    field = models.ForeignKey(ProfileField, on_delete=models.CASCADE, related_name="values")
    value = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "field"], name="one_value_per_user_field")]
