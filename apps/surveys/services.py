from collections import Counter

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.courses import permissions as perm
from apps.courses.models import Enrolment

from .models import Answer, Submission, Survey, SurveyQuestion

MAX_TEXT = 2000


def state(survey, now=None):
    now = now or timezone.now()
    if survey.opens_at and now < survey.opens_at:
        return "not_open"
    if survey.closes_at and now >= survey.closes_at:
        return "closed"
    return "open"


def visible_for_student(user):
    courses = perm.visible_courses_for(user)
    return Survey.objects.filter(course__in=courses, is_visible=True).select_related("course")


def has_answered(survey, user):
    return Submission.objects.filter(survey=survey, student=user).exists()


def can_see_results(survey, user):
    if survey.show_results == "never":
        return False
    if survey.show_results == "after_close":
        return state(survey) == "closed"
    return has_answered(survey, user)


def enrolled_students(course):
    return [e.user for e in Enrolment.objects.filter(course=course, status=Enrolment.Status.ACTIVE, user__role="student", user__is_active=True).select_related("user")]


def parse(survey, post):
    """Return (clean {question_id: [values]}, errors {question_id: message}) from posted data."""
    clean, errors = {}, {}
    for q in survey.questions.all():
        key = f"q{q.pk}"
        if q.kind == "multiple":
            vals = [v for v in post.getlist(key) if v in q.choice_list]
        elif q.kind == "single":
            v = post.get(key, "")
            vals = [v] if v in q.choice_list else []
        elif q.kind == "rating":
            v = post.get(key, "")
            vals = [v] if v in {"1", "2", "3", "4", "5"} else []
        else:
            v = (post.get(key) or "").strip()
            vals = [v[:MAX_TEXT]] if v else []
        if not vals and q.required:
            errors[q.pk] = "Please answer this question."
        clean[q.pk] = vals
    return clean, errors


def submit(survey, student, clean):
    """Save one student's answers. Returns False when they already answered."""
    try:
        with transaction.atomic():
            sub = Submission.objects.create(survey=survey, student=student)
            link = None if survey.anonymous else sub
            Answer.objects.bulk_create([Answer(question_id=qid, submission=link, value=v) for qid, vals in clean.items() for v in vals])
        return True
    except IntegrityError:
        return False


def results(survey):
    total = survey.submissions.count()
    out = []
    for q in survey.questions.all():
        values = list(q.answers.values_list("value", flat=True))
        row = {"question": q}
        if q.kind in ("single", "multiple"):
            counts = Counter(values)
            row["bars"] = [{"label": c, "count": counts.get(c, 0), "pct": round(100 * counts.get(c, 0) / total) if total else 0} for c in q.choice_list]
        elif q.kind == "rating":
            counts = Counter(values)
            n = len(values)
            row["bars"] = [{"label": str(i), "count": counts.get(str(i), 0), "pct": round(100 * counts.get(str(i), 0) / n) if n else 0} for i in range(5, 0, -1)]
            row["average"] = round(sum(int(v) for v in values) / n, 2) if n else None
            row["answered"] = n
        else:
            row["texts"] = sorted(values) if survey.anonymous else values
            row["answered"] = len(values)
        out.append(row)
    return {"total": total, "rows": out, "rated": [r for r in out if r.get("average")]}


def participants(survey):
    """(took part, did not) among active students. Staff only."""
    students = enrolled_students(survey.course)
    done = set(survey.submissions.values_list("student_id", flat=True))
    return [s for s in students if s.pk in done], [s for s in students if s.pk not in done]


def question_locked(survey):
    return survey.submissions.exists()
