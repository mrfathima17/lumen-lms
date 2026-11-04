from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import SiteSettings
from apps.courses.models import Course


class Quiz(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="quizzes")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    time_limit_minutes = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Leave empty for no time limit.")
    opens_at = models.DateTimeField(null=True, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)
    max_attempts = models.PositiveSmallIntegerField(default=1)
    is_visible = models.BooleanField(default=True, help_text="Students can see the quiz.")
    is_enabled = models.BooleanField(default=True, help_text="Students can start attempts. Turn off to pause the quiz.")
    review_policy = models.CharField(max_length=20, blank=True, choices=SiteSettings.QuizReview.choices,
                                     help_text="When students may see correct answers. Empty uses the system default.")
    review_released = models.BooleanField(default=False, help_text="Used when the review policy is 'When the lecturer releases it'.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["closes_at", "id"]
        verbose_name_plural = "quizzes"

    def __str__(self):
        return f"{self.course.code} · {self.title}"

    @property
    def total_marks(self):
        return self.questions.aggregate(t=models.Sum("marks"))["t"] or Decimal("0")

    @property
    def effective_review_policy(self):
        return self.review_policy or SiteSettings.load().quiz_review_policy


class Question(models.Model):
    class Kind(models.TextChoices):
        MCQ = "mcq", "Multiple choice (one answer)"
        TF = "tf", "True or false"
        SHORT = "short", "Short answer"
        ESSAY = "essay", "Written answer (marked by hand)"

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    kind = models.CharField(max_length=6, choices=Kind.choices, default=Kind.MCQ)
    text = models.TextField()
    marks = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    position = models.PositiveIntegerField(default=0)
    accepted_answers = models.TextField(blank=True, help_text="Short answers: one accepted answer per line (not case sensitive). Leave empty to mark by hand.")

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.text[:60]

    @property
    def auto_marked(self):
        if self.kind in (self.Kind.MCQ, self.Kind.TF):
            return True
        return self.kind == self.Kind.SHORT and bool(self.accepted_answers.strip())


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]


class Attempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        SUBMITTED = "submitted", "Waiting for marking"
        GRADED = "graded", "Marked"

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quiz_attempts")
    number = models.PositiveSmallIntegerField(default=1)
    started_at = models.DateTimeField()
    deadline_at = models.DateTimeField(null=True, blank=True, help_text="Set by the server when the attempt starts.")
    submitted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_PROGRESS)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["started_at"]
        constraints = [models.UniqueConstraint(fields=["quiz", "student", "number"], name="uniq_attempt_number")]

    @property
    def taken_label(self):
        """Time between starting and submitting, as m:ss (h:mm:ss over an hour)."""
        if not self.submitted_at:
            return "—"
        secs = max(0, int((self.submitted_at - self.started_at).total_seconds()))
        h, rest = divmod(secs, 3600)
        m, s = divmod(rest, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def __str__(self):
        return f"{self.student} · {self.quiz} #{self.number}"


class Answer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    choice = models.ForeignKey(Choice, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    text = models.TextField(blank=True)
    awarded = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    feedback = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["attempt", "question"], name="uniq_answer_per_question")]


class BankQuestion(models.Model):
    """A reusable question kept per course. Copying it into a quiz makes an independent Question, so editing the bank never changes a running quiz."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="bank_questions")
    category = models.CharField(max_length=80, blank=True, help_text="Optional topic label, such as 'Normalisation'.")
    kind = models.CharField(max_length=6, choices=Question.Kind.choices, default=Question.Kind.MCQ)
    text = models.TextField()
    marks = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    accepted_answers = models.TextField(blank=True)
    choices = models.JSONField(default=list, blank=True)  # [{"text": "...", "correct": true}]
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "id"]

    def __str__(self):
        return self.text[:60]
