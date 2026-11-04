from django.conf import settings
from django.db import models

from apps.assignments.models import Assignment
from apps.courses.models import Course
from apps.quizzes.models import Quiz


class GradeBand(models.Model):
    """One row of the grade scale: from this percentage upward the student gets this letter and these grade points."""

    min_percent = models.DecimalField(max_digits=5, decimal_places=2, unique=True)
    letter = models.CharField(max_length=3)
    points = models.DecimalField(max_digits=3, decimal_places=2)

    class Meta:
        ordering = ["-min_percent"]

    def __str__(self):
        return f"{self.letter} from {self.min_percent}% ({self.points} points)"


class GradeItem(models.Model):
    """One graded component of a course. It points at an assignment, a quiz, or is a manual item such as an exam."""

    class Kind(models.TextChoices):
        ASSIGNMENT = "assignment", "Assignment"
        QUIZ = "quiz", "Quiz"
        MANUAL = "manual", "Manual (exam, viva, ...)"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="grade_items")
    title = models.CharField(max_length=150)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    assignment = models.OneToOneField(Assignment, null=True, blank=True, on_delete=models.CASCADE, related_name="grade_item")
    quiz = models.OneToOneField(Quiz, null=True, blank=True, on_delete=models.CASCADE, related_name="grade_item")
    max_mark = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Manual items only.")
    weight = models.DecimalField(max_digits=5, decimal_places=2, help_text="Share of the course mark, in percent.")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.course.code} · {self.title}"


class ManualMark(models.Model):
    item = models.ForeignKey(GradeItem, on_delete=models.CASCADE, related_name="marks")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="manual_marks")
    mark = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["item", "student"], name="uniq_manual_mark")]


class CourseResult(models.Model):
    """A published final result. Frozen when the lecturer publishes, so later edits never silently change a transcript."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="results")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="course_results")
    percent = models.DecimalField(max_digits=5, decimal_places=2)
    letter = models.CharField(max_length=3)
    points = models.DecimalField(max_digits=3, decimal_places=2)
    credits = models.PositiveSmallIntegerField()
    published_at = models.DateTimeField()
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["course__semester__name", "course__code"]
        constraints = [models.UniqueConstraint(fields=["course", "student"], name="uniq_course_result")]
