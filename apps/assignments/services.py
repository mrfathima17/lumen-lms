"""Assignment business rules. Views stay thin; every rule here is covered by tests."""
import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.models import SiteSettings
from apps.courses.permissions import is_enrolled

from .models import Extension, Submission


class SubmissionError(Exception):
    """Raised with a message that is safe to show the student."""


def effective_due(assignment, student):
    """The student's own deadline: an extension counts only if it is later than the normal one."""
    ext = Extension.objects.filter(assignment=assignment, student=student).first()
    if ext and ext.due_at > assignment.due_at:
        return ext.due_at
    return assignment.due_at


def days_late(due, when):
    """Whole days past the deadline, counting any started day (1 minute late = 1 day). 0 when on time."""
    if when <= due:
        return 0
    return math.ceil((when - due) / timedelta(days=1))


def penalty_for(late_days, rate=None):
    rate = SiteSettings.load().late_penalty_percent_per_day if rate is None else rate
    return min(100, late_days * rate)


def apply_penalty(raw, percent):
    return (Decimal(raw) * (100 - percent) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@transaction.atomic
def submit(assignment, student, file, comment="", now=None):
    now = now or timezone.now()
    if not assignment.is_visible or not is_enrolled(student, assignment.course):
        raise SubmissionError("You cannot submit to this assignment.")
    due = effective_due(assignment, student)
    late = days_late(due, now)
    if late and not assignment.allow_late:
        raise SubmissionError("The deadline has passed and this assignment does not accept late work.")
    existing = Submission.objects.select_for_update().filter(assignment=assignment, student=student).first()
    if existing and existing.status == Submission.Status.GRADED:
        raise SubmissionError("This submission has already been graded and can no longer be changed.")
    if existing:
        if existing.file:
            existing.file.delete(save=False)
        existing.file, existing.comment, existing.submitted_at, existing.late_days = file, comment, now, late
        existing.save()
        return existing
    return Submission.objects.create(assignment=assignment, student=student, file=file, comment=comment, submitted_at=now, late_days=late)


@transaction.atomic
def grade(submission, raw_mark, feedback, grader, now=None):
    raw = Decimal(raw_mark)
    if raw < 0 or raw > submission.assignment.max_mark:
        raise ValueError(f"Mark must be between 0 and {submission.assignment.max_mark}.")
    pct = penalty_for(submission.late_days)
    submission.raw_mark, submission.penalty_percent = raw, pct
    submission.final_mark = apply_penalty(raw, pct)
    submission.feedback, submission.graded_by = feedback, grader
    submission.graded_at = now or timezone.now()
    submission.status = Submission.Status.GRADED
    submission.save()
    from apps.messaging.services import notify  # local import: messaging depends on courses, not the other way round

    notify([submission.student], f"Your work for {submission.assignment.title} has been graded", f"/assignments/{submission.assignment_id}/", "grade")
    return submission
