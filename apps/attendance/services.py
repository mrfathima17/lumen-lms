"""Attendance rules.

Present and late count as attended. Excused sessions are left out of the count entirely (they neither help nor hurt).
A session only counts for a student once the sheet has been saved with a record for them.
"""
import math
from collections import defaultdict
from decimal import Decimal

from django.db import transaction

from apps.core.models import SiteSettings
from apps.courses.models import Enrolment

from .models import AttendanceRecord as R

VALID = {c for c, _ in R.Status.choices}


def threshold():
    return SiteSettings.load().attendance_warning_percent


def stats(statuses):
    """statuses: iterable of status strings -> dict of counts, counted sessions and percent (None when nothing counts)."""
    c = defaultdict(int)
    for s in statuses:
        c[s] += 1
    counted = c["present"] + c["late"] + c["absent"]
    attended = c["present"] + c["late"]
    pct = (Decimal(attended) * 100 / counted).quantize(Decimal("0.1")) if counted else None
    return {"present": c["present"], "late": c["late"], "absent": c["absent"], "excused": c["excused"],
            "counted": counted, "attended": attended, "percent": pct}


def level(percent, limit=None):
    """'ok', 'warn' (within 5 points above the limit), 'bad' (below it) or 'mute' (no data)."""
    limit = threshold() if limit is None else limit
    if percent is None:
        return "mute"
    if percent < limit:
        return "bad"
    return "warn" if percent < limit + 5 else "ok"


def sessions_needed(st, limit=None):
    """How many further sessions attended in a row bring the student up to the limit (0 when already there)."""
    limit = threshold() if limit is None else limit
    if st["percent"] is None or st["percent"] >= limit or limit >= 100:
        return 0
    return max(0, math.ceil((limit * st["counted"] - 100 * st["attended"]) / (100 - limit)))


def active_students(course):
    return [e.user for e in Enrolment.objects.filter(course=course, status=Enrolment.Status.ACTIVE).select_related("user").order_by("user__first_name", "user__last_name", "user__username")]


def student_course_stats(course, student):
    return stats(R.objects.filter(session__course=course, student=student).values_list("status", flat=True))


def course_overview(course):
    """Rows for the lecturer: every active student with their overall figures for the course."""
    students = active_students(course)
    by = defaultdict(list)
    for sid, status in R.objects.filter(session__course=course, student__in=students).values_list("student_id", "status"):
        by[sid].append(status)
    limit = threshold()
    rows = []
    for s in students:
        st = stats(by[s.pk])
        rows.append({"student": s, "stats": st, "level": level(st["percent"], limit), "below": st["percent"] is not None and st["percent"] < limit})
    return rows


@transaction.atomic
def save_sheet(session, posted):
    """posted: {student_id: status}. Only active students of this course are accepted; returns the number saved.
    Raises ValueError (and saves nothing) for an unknown status or a student who is not enrolled."""
    allowed = {s.pk for s in active_students(session.course)}
    clean = {}
    for sid, status in posted.items():
        if status not in VALID:
            raise ValueError("Unknown attendance status.")
        if sid not in allowed:
            raise ValueError("That student is not enrolled in this course.")
        clean[sid] = status
    for sid, status in clean.items():
        R.objects.update_or_create(session=session, student_id=sid, defaults={"status": status})
    return len(clean)
