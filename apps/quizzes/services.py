"""Quiz rules. The server owns the clock: the student's browser only displays it."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.models import SiteSettings
from apps.courses.permissions import is_enrolled

from .models import Answer, Attempt, Choice, Question, Quiz


class QuizError(Exception):
    """Message is safe to show the student."""


def availability(quiz, now=None):
    """Return (is_open, reason). Reason explains why not."""
    now = now or timezone.now()
    if not quiz.is_visible:
        return False, "This quiz is not available."
    if not quiz.is_enabled:
        return False, "This quiz is paused by your lecturer."
    if quiz.opens_at and now < quiz.opens_at:
        return False, "This quiz has not opened yet."
    if quiz.closes_at and now >= quiz.closes_at:
        return False, "This quiz has closed."
    if not quiz.questions.exists():
        return False, "This quiz has no questions yet."
    return True, ""


def compute_deadline(quiz, started_at):
    candidates = []
    if quiz.time_limit_minutes:
        candidates.append(started_at + timedelta(minutes=quiz.time_limit_minutes))
    if quiz.closes_at:
        candidates.append(quiz.closes_at)
    return min(candidates) if candidates else None


def in_progress_attempt(quiz, student):
    return Attempt.objects.filter(quiz=quiz, student=student, status=Attempt.Status.IN_PROGRESS).first()


@transaction.atomic
def start_attempt(quiz, student, now=None):
    now = now or timezone.now()
    if not is_enrolled(student, quiz.course):
        raise QuizError("You are not enrolled in this course.")
    existing = in_progress_attempt(quiz, student)
    if existing:
        return existing  # resume, never open a second one
    ok, reason = availability(quiz, now)
    if not ok:
        raise QuizError(reason)
    used = Attempt.objects.select_for_update().filter(quiz=quiz, student=student).count()
    if used >= quiz.max_attempts:
        raise QuizError("You have used all your attempts.")
    return Attempt.objects.create(quiz=quiz, student=student, number=used + 1, started_at=now, deadline_at=compute_deadline(quiz, now))


def seconds_left(attempt, now=None):
    if attempt.deadline_at is None:
        return None
    return max(0, int((attempt.deadline_at - (now or timezone.now())).total_seconds()))


def expired(attempt, now=None):
    return attempt.deadline_at is not None and (now or timezone.now()) >= attempt.deadline_at


def save_answer(attempt, question, *, choice_id=None, text="", now=None):
    now = now or timezone.now()
    if attempt.status != Attempt.Status.IN_PROGRESS:
        raise QuizError("This attempt is already submitted.")
    if expired(attempt, now):
        raise QuizError("Time is up. Your earlier answers were saved.")
    if question.quiz_id != attempt.quiz_id:
        raise QuizError("That question is not part of this quiz.")
    choice = None
    if question.kind in (Question.Kind.MCQ, Question.Kind.TF):
        if choice_id in (None, ""):
            Answer.objects.filter(attempt=attempt, question=question).delete()
            return None
        choice = Choice.objects.filter(pk=choice_id, question=question).first()
        if not choice:
            raise QuizError("That choice does not belong to this question.")
        text = ""
    else:
        text = (text or "")[:5000]
    ans, _ = Answer.objects.update_or_create(attempt=attempt, question=question, defaults={"choice": choice, "text": text, "awarded": None, "feedback": ""})
    return ans


def _normalise(s):
    return " ".join((s or "").lower().split())


def _mark_answer(ans):
    q = ans.question
    if q.kind in (Question.Kind.MCQ, Question.Kind.TF):
        ans.awarded = q.marks if ans.choice and ans.choice.is_correct else Decimal("0")
    elif q.kind == Question.Kind.SHORT and q.auto_marked:
        accepted = {_normalise(x) for x in q.accepted_answers.splitlines() if x.strip()}
        ans.awarded = q.marks if _normalise(ans.text) in accepted else Decimal("0")
    else:
        ans.awarded = None  # waits for the lecturer
    ans.save(update_fields=["awarded"])


def recompute(attempt):
    """Sum awarded marks; the attempt counts as marked only when no written answer is still waiting."""
    answers = {a.question_id: a for a in attempt.answers.select_related("question")}
    pending = False
    total = Decimal("0")
    for q in attempt.quiz.questions.all():
        a = answers.get(q.pk)
        if a is None:
            continue  # unanswered: scores zero and never waits for marking
        if a.awarded is None:
            pending = True
        else:
            total += a.awarded
    attempt.score = total
    attempt.status = Attempt.Status.SUBMITTED if pending else Attempt.Status.GRADED
    attempt.save(update_fields=["score", "status"])
    return attempt


@transaction.atomic
def finish_attempt(attempt, now=None):
    """Submit and auto-mark. Safe to call twice. A late finish is recorded at the deadline, not the click."""
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return attempt
    now = now or timezone.now()
    attempt.submitted_at = min(now, attempt.deadline_at) if attempt.deadline_at else now
    for ans in attempt.answers.select_related("question", "choice"):
        _mark_answer(ans)
    return recompute(attempt)


def expire_overdue(now=None):
    """Submit every attempt whose time ran out (called by the close_expired_attempts command and lazily by views)."""
    now = now or timezone.now()
    n = 0
    for a in Attempt.objects.filter(status=Attempt.Status.IN_PROGRESS, deadline_at__lte=now):
        finish_attempt(a, now)
        n += 1
    return n


def manual_grade(attempt, marks_by_answer, feedback_by_answer=None):
    """marks_by_answer: {answer_id: Decimal}. Each mark is limited to the question's marks."""
    feedback_by_answer = feedback_by_answer or {}
    with transaction.atomic():
        for ans in attempt.answers.select_related("question"):
            if ans.pk in marks_by_answer:
                m = Decimal(marks_by_answer[ans.pk])
                if m < 0 or m > ans.question.marks:
                    raise ValueError(f"Mark for question must be between 0 and {ans.question.marks}.")
                ans.awarded = m
                ans.feedback = feedback_by_answer.get(ans.pk, ans.feedback)
                ans.save(update_fields=["awarded", "feedback"])
        return recompute(attempt)


def regrade(attempt):
    """Re-mark every automatically marked answer (after the lecturer fixed a correct answer); hand-marked answers keep their marks."""
    for ans in attempt.answers.select_related("question", "choice"):
        if ans.question.auto_marked:
            _mark_answer(ans)
    return recompute(attempt)


def review_allowed(quiz, attempt, now=None):
    """Correct answers are revealed only after submission and according to the quiz or system policy."""
    now = now or timezone.now()
    if attempt.status == Attempt.Status.IN_PROGRESS:
        return False
    policy = quiz.effective_review_policy
    Q = SiteSettings.QuizReview
    if policy == Q.IMMEDIATE:
        return True
    if policy == Q.MANUAL:
        return quiz.review_released
    # after the quiz closes; with no closing date there is nothing to wait for
    return quiz.closes_at is None or now >= quiz.closes_at
