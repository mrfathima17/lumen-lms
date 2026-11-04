from django.conf import settings
from django.db import models

from apps.courses.models import Course


class Survey(models.Model):
    """A poll (one question) or a survey (several) set inside a course."""

    class Kind(models.TextChoices):
        POLL = "poll", "Poll"
        SURVEY = "survey", "Survey"

    class Results(models.TextChoices):
        NEVER = "never", "Never (staff only)"
        AFTER_VOTE = "after_vote", "After the student has answered"
        AFTER_CLOSE = "after_close", "After the survey closes"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="surveys")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SURVEY)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_visible = models.BooleanField(default=False, help_text="Students can see and answer it only when this is on.")
    opens_at = models.DateTimeField(null=True, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)
    anonymous = models.BooleanField(default=False, help_text="Answers are stored without the student's name. Staff still see who took part.")
    show_results = models.CharField(max_length=12, choices=Results.choices, default=Results.NEVER)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class SurveyQuestion(models.Model):
    class Kind(models.TextChoices):
        SINGLE = "single", "Choose one"
        MULTIPLE = "multiple", "Choose any"
        RATING = "rating", "Rating 1 to 5"
        TEXT = "text", "Written answer"

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="questions")
    position = models.PositiveIntegerField(default=0)
    text = models.CharField(max_length=300)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SINGLE)
    required = models.BooleanField(default=True)
    choices = models.TextField(blank=True, help_text="One choice per line.")

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.text

    @property
    def choice_list(self):
        return [c.strip() for c in self.choices.splitlines() if c.strip()]


class Submission(models.Model):
    """Records that a student took part. For an anonymous survey the answers carry no link back to this row."""

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="survey_submissions")
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["survey", "student"], name="one_submission_per_survey_student")]


class Answer(models.Model):
    question = models.ForeignKey(SurveyQuestion, on_delete=models.CASCADE, related_name="answers")
    submission = models.ForeignKey(Submission, null=True, blank=True, on_delete=models.CASCADE, related_name="answers")
    value = models.TextField()  # the chosen text, the rating digit, or the written answer; one row per choice for "choose any"
