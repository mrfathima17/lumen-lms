"""Numbers and lists for the three dashboards. Read-only; every query is limited to what the person may see."""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.assignments.models import Submission
from apps.completion import services as completion
from apps.core.models import AllowedNetwork
from apps.courses import permissions as perm
from apps.courses.models import Enrolment
from apps.grading import services as grading
from apps.messaging.services import announcements_for
from apps.quizzes.models import Quiz
from apps.schedule.services import deadlines_for, timetable_for


def greeting(user):
    hour = timezone.localtime().hour
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    return f"Good {part}, {user.first_name or user.username}"


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _open_quizzes(course_ids):
    now = timezone.now()
    return Quiz.objects.filter(course_id__in=course_ids, is_visible=True, is_enabled=True).filter(
        Q(opens_at__isnull=True) | Q(opens_at__lte=now), Q(closes_at__isnull=True) | Q(closes_at__gte=now))


def _due_label(at, kind, today):
    """(pill level, text) for one deadline."""
    days = (at.date() - today).days
    if days <= 0:
        return "warn", "Due today"
    if days == 1:
        return "warn", "Due tomorrow"
    return ("ok", "Open") if kind == "q" else ("mute", f"In {days} days")


def _classes(user):
    """Today's classes still ahead or running, plus the next one after those."""
    now = timezone.localtime()
    days = timetable_for(user)
    today = [s for d in days if d["weekday"] == now.weekday() for s in d["slots"]]
    left = [s for s in today if s.end_time > now.time()]
    nxt = None
    order = [d for d in days if d["weekday"] > now.weekday()] + [d for d in days if d["weekday"] <= now.weekday()]
    for d in order:
        if d["weekday"] == now.weekday():
            continue
        if d["slots"]:
            nxt = (d["name"], d["slots"][0])
            break
    return left, nxt


def student_context(user):
    ids = list(perm.visible_courses_for(user).values_list("pk", flat=True))
    courses = perm.visible_courses_for(user).select_related("department", "semester").prefetch_related("lecturers")
    cards = []
    for c in courses:
        ev = completion.evaluate(c, user)
        lecturers = list(c.lecturers.all())
        cards.append({"course": c, "lecturer": lecturers[0] if lecturers else None, "progress": ev["percent"] if ev["tracked"] else None})
    today = timezone.localdate()
    deadlines = deadlines_for(user, 14)
    for d in deadlines:
        d["level"], d["label"] = _due_label(d["at"], d["kind"], today)
    week = [d for d in deadlines if d["kind"] == "a" and (d["at"].date() - today).days <= 7]
    open_quizzes = _open_quizzes(ids).count()
    _, cumulative, _ = grading.results_by_semester(user)
    if week or open_quizzes:
        quizzes = f"{open_quizzes} quiz{'' if open_quizzes == 1 else 'zes'}"
        sub = f"You have {_plural(len(week), 'assignment')} due this week and {quizzes} open."
    else:
        sub = "Nothing is due this week."
    left, nxt = _classes(user)
    return {
        "greeting": greeting(user), "sub": sub, "cards": cards, "deadlines": deadlines[:5], "announcements": list(announcements_for(user, drafts=False)[:3]),
        "stats": {"courses": len(cards), "due": len(week), "quizzes": open_quizzes, "gpa": cumulative},
        "classes_today": left, "class_next": nxt, "tracked": [c for c in cards if c["progress"] is not None],
    }


def lecturer_context(user):
    courses = list(perm.visible_courses_for(user).order_by("code"))
    ids = [c.pk for c in courses]
    subs = Submission.objects.filter(assignment__course_id__in=ids)
    quiz_rules = AllowedNetwork.objects.filter(scope="quiz", is_active=True).exists()
    return {
        "greeting": f"Welcome, {user.get_full_name() or user.username}",
        "sub": ", ".join(f"{c.code} · {c.title}" for c in courses[:1]) + (f" and {len(courses) - 1} more" if len(courses) > 1 else "") if courses else "You are not teaching any course yet.",
        "stats": {
            "students": Enrolment.objects.filter(course_id__in=ids, status="active").values("user").distinct().count(),
            "submissions": subs.count(), "to_grade": subs.filter(status="submitted").count(),
            "quizzes": _open_quizzes(ids).count(),
        },
        "quizzes": list(Quiz.objects.filter(course_id__in=ids).select_related("course").order_by("-created_at")[:6]),
        "quiz_rules": quiz_rules,
        "submissions": list(subs.select_related("student", "assignment__course").order_by("status", "-submitted_at")[:8]),
        "has_courses": bool(courses),
    }
