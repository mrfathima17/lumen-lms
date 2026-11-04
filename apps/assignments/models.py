from django.conf import settings
from django.db import models

from apps.core.uploads import original_filename, upload_path, validate_upload
from apps.courses.models import Course, Topic


class Assignment(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="assignments")
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.SET_NULL, related_name="assignments")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    due_at = models.DateTimeField()
    max_mark = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    allow_late = models.BooleanField(default=True, help_text="Late work is accepted and loses marks per day (see system settings).")
    is_visible = models.BooleanField(default=True)
    allowed_types = models.CharField("Allowed file types", max_length=120, blank=True, help_text="Comma-separated, e.g. pdf, docx, zip. Leave empty to accept every supported type.")
    max_file_mb = models.PositiveSmallIntegerField("Max file size (MB)", default=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_at", "id"]

    @property
    def allowed_extensions(self):
        return [e.strip().lstrip(".").lower() for e in self.allowed_types.replace(";", ",").split(",") if e.strip()]

    def __str__(self):
        return f"{self.course.code} · {self.title}"


class Submission(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        GRADED = "graded", "Graded"

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions")
    file = models.FileField(upload_to=upload_path("submissions"), validators=[validate_upload])
    comment = models.CharField(max_length=500, blank=True)
    submitted_at = models.DateTimeField()
    late_days = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED)
    raw_mark = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    penalty_percent = models.PositiveSmallIntegerField(default=0)
    final_mark = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["submitted_at"]
        constraints = [models.UniqueConstraint(fields=["assignment", "student"], name="uniq_submission_per_student")]

    def __str__(self):
        return f"{self.student} → {self.assignment}"

    @property
    def original_name(self):
        return original_filename(self.file.name)

    @property
    def file_size(self):
        """Size in bytes, or None when the stored file cannot be found (so a missing file never breaks a page)."""
        try:
            return self.file.size
        except (OSError, ValueError):
            return None


class Extension(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="extensions")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="extensions")
    due_at = models.DateTimeField()
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["assignment", "student"], name="uniq_extension_per_student")]


class RubricCriterion(models.Model):
    """One row of an assignment's marking rubric. Its levels are the choices a marker picks from."""

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="criteria")
    position = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=150)
    description = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.title

    @property
    def max_points(self):
        return max((lv.points for lv in self.levels.all()), default=0)


class RubricLevel(models.Model):
    criterion = models.ForeignKey(RubricCriterion, on_delete=models.CASCADE, related_name="levels")
    label = models.CharField(max_length=80)
    points = models.DecimalField(max_digits=6, decimal_places=2)
    description = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-points", "id"]


class RubricScore(models.Model):
    """The level a marker picked for one criterion of one submission. Label and points are copied so the record stays true if the rubric is ever copied or replaced."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="rubric_scores")
    criterion = models.ForeignKey(RubricCriterion, on_delete=models.CASCADE, related_name="scores")
    level = models.ForeignKey(RubricLevel, null=True, on_delete=models.SET_NULL, related_name="+")
    label = models.CharField(max_length=80)
    points = models.DecimalField(max_digits=6, decimal_places=2)
    comment = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["submission", "criterion"], name="uniq_score_per_criterion")]
