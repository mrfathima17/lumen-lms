import secrets

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models

from apps.courses.models import Course

PCT = [MaxValueValidator(100)]
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I so codes can be read out over the phone


def new_code():
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


class CompletionRule(models.Model):
    """What a student must do to complete a course. Empty (off) rules are ignored; with no rule on, completion is not tracked."""

    course = models.OneToOneField(Course, on_delete=models.CASCADE, related_name="completion_rule")
    require_assignments = models.BooleanField(default=False, help_text="Submit every visible assignment.")
    min_quiz_percent = models.PositiveSmallIntegerField(null=True, blank=True, validators=PCT, help_text="Average of the best attempt on every visible quiz (a quiz not attempted counts as 0). Leave empty to switch off.")
    min_attendance_percent = models.PositiveSmallIntegerField(null=True, blank=True, validators=PCT, help_text="Attendance percentage (excused sessions left out). Leave empty to switch off.")
    min_final_percent = models.PositiveSmallIntegerField(null=True, blank=True, validators=PCT, help_text="Weighted gradebook percentage. Leave empty to switch off.")
    auto_certificate = models.BooleanField(default=True, help_text="Issue a certificate automatically when a student completes the course.")

    def __str__(self):
        return f"Completion rule for {self.course.code}"

    @property
    def any_rule(self):
        return self.require_assignments or any(v is not None for v in (self.min_quiz_percent, self.min_attendance_percent, self.min_final_percent))


class Certificate(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="certificates")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="certificates")
    code = models.CharField(max_length=14, unique=True, default=new_code, editable=False)
    issued_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    # Frozen at issue time so a later rename of the course or user does not change a printed certificate.
    student_name = models.CharField(max_length=150)
    course_title = models.CharField(max_length=150)
    course_code = models.CharField(max_length=20)

    class Meta:
        ordering = ["-issued_at"]
        constraints = [models.UniqueConstraint(fields=["course", "student"], name="one_certificate_per_course_student")]

    def __str__(self):
        return f"{self.code} · {self.student_name} · {self.course_code}"

    @property
    def is_valid(self):
        return self.revoked_at is None
