"""What appears on a person's calendar, timetable and to-do list.

Deadlines are read live from assignments and quizzes, so they can never drift from the real due dates.
"""
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.db.models import Q
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.courses import permissions as perm
from apps.quizzes.models import Quiz

from .models import Event, TimetableSlot


def _course_ids(user):
    return list(perm.visible_courses_for(user).values_list("pk", flat=True))


def _local(dt):
    return timezone.localtime(dt)


def _day_bounds(start, end):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(start, time.min), tz), timezone.make_aware(datetime.combine(end, time.min), tz)


def calendar_items(user, start, end):
    """Items for the dates start <= d < end, as dicts sorted by time. kind: a assignment, q quiz, c class, e event."""
    ids = _course_ids(user)
    lo, hi = _day_bounds(start, end)
    staff = user.role != "student"
    items = []
    a_qs = Assignment.objects.filter(course_id__in=ids, due_at__gte=lo, due_at__lt=hi).select_related("course")
    q_qs = Quiz.objects.filter(course_id__in=ids, closes_at__gte=lo, closes_at__lt=hi).select_related("course")
    if not staff:
        a_qs, q_qs = a_qs.filter(is_visible=True), q_qs.filter(is_visible=True)
    for a in a_qs:
        items.append({"kind": "a", "at": _local(a.due_at), "title": a.title, "course": a.course.code, "label": "Due", "url_name": "assignments:submissions" if staff else "assignments:detail", "pk": a.pk})
    for q in q_qs:
        items.append({"kind": "q", "at": _local(q.closes_at), "title": q.title, "course": q.course.code, "label": "Closes", "url_name": "quizzes:editor" if staff else "quizzes:student-detail", "pk": q.pk})
    ev = Event.objects.filter(starts_at__gte=lo, starts_at__lt=hi).filter(Q(owner=user, course__isnull=True) | Q(course_id__in=ids)).select_related("course")
    for e in ev:
        items.append({"kind": "e", "at": _local(e.starts_at), "title": e.title, "course": e.course.code if e.course_id else "Personal", "label": "", "event": e})
    for slot in TimetableSlot.objects.filter(course_id__in=ids).select_related("course"):
        d = start + timedelta(days=(slot.weekday - start.weekday()) % 7)
        while d < end:
            at = timezone.make_aware(datetime.combine(d, slot.start_time), timezone.get_current_timezone())
            items.append({"kind": "c", "at": at, "title": f"{slot.course.code} {slot.get_kind_display()}", "course": slot.course.code, "label": slot.room, "slot": slot})
            d += timedelta(days=7)
    items.sort(key=lambda i: (i["at"], i["title"]))
    return items


def month_grid(user, year, month):
    """Weeks (Monday first) of day cells for one month, each with its items."""
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    grid_start = first - timedelta(days=first.weekday())
    grid_end = nxt + timedelta(days=(7 - nxt.weekday()) % 7)
    by_day = {}
    for it in calendar_items(user, grid_start, grid_end):
        by_day.setdefault(it["at"].date(), []).append(it)
    today = timezone.localdate()
    days, d = [], grid_start
    while d < grid_end:
        days.append({"date": d, "off": d.month != month, "today": d == today, "items": by_day.get(d, [])})
        d += timedelta(days=1)
    return days


def week_start(day):
    return day - timedelta(days=day.weekday())


def timetable_for(user):
    """Weekly slots grouped by weekday (0 to 6), only weekdays that have classes."""
    slots = TimetableSlot.objects.filter(course_id__in=_course_ids(user)).select_related("course")
    days = {}
    for s in slots:
        days.setdefault(s.weekday, []).append(s)
    return [{"weekday": w, "name": TimetableSlot.Weekday(w).label, "slots": sorted(v, key=lambda s: s.start_time)} for w, v in sorted(days.items())]


def timetable_grid(user, offset=0):
    """Everything the weekly grid needs: Monday to Friday (plus any weekend day that has a class), half-hour rows,
    each class placed by row and column, and the side cards (today, up next, courses). Classes repeat every week,
    so the week only decides which dates are written in the headings."""
    slots = list(TimetableSlot.objects.filter(course_id__in=_course_ids(user)).select_related("course").prefetch_related("course__lecturers"))
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    last = max([4] + [s.weekday for s in slots])
    cols = [{"weekday": w, "name": TimetableSlot.Weekday(w).label[:3], "date": monday + timedelta(days=w), "today": monday + timedelta(days=w) == today, "col": w + 2} for w in range(last + 1)]
    start_h = min([s.start_time.hour for s in slots] + [8])
    end_h = max([s.end_time.hour + (1 if s.end_time.minute else 0) for s in slots] + [17])
    hours = [{"label": time(h).strftime("%I %p").lstrip("0"), "row": 2 + (h - start_h) * 2} for h in range(start_h, end_h)]
    events = []
    for n, s in enumerate(sorted(slots, key=lambda s: (s.weekday, s.start_time))):
        first = (s.start_time.hour - start_h) * 2 + (1 if s.start_time.minute >= 30 else 0)
        stop = (s.end_time.hour - start_h) * 2 + (1 if 0 < s.end_time.minute <= 30 else 2 if s.end_time.minute > 30 else 0)
        events.append({"slot": s, "col": s.weekday + 2, "row": 2 + first, "span": max(1, stop - first), "tone": s.course.tone})
    now = timezone.localtime()
    todays = [s for s in slots if s.weekday == now.weekday()]
    todays.sort(key=lambda s: s.start_time)
    upcoming = sorted(slots, key=lambda s: ((s.weekday - now.weekday()) % 7 if (s.weekday != now.weekday() or s.start_time > now.time()) else 7, s.start_time))
    up_next = next((s for s in upcoming if s.weekday != now.weekday() or s.start_time > now.time()), None)
    courses = {s.course_id: s.course for s in slots}
    return {"cols": cols, "hours": hours, "events": events, "rows": (end_h - start_h) * 2, "cells": [{"col": c["col"], "row": h["row"], "today": c["today"]} for c in cols for h in hours],
            "monday": monday, "friday": monday + timedelta(days=last), "todays": todays, "up_next": up_next, "slots_exist": bool(slots),
            "courses": sorted(courses.values(), key=lambda c: c.code), "today": today}


def deadlines_for(student, days=30):
    """Upcoming assignment and quiz deadlines for a student that still need action."""
    ids = _course_ids(student)
    now = timezone.now()
    done = set(Submission.objects.filter(student=student).values_list("assignment_id", flat=True))
    out = []
    for a in Assignment.objects.filter(course_id__in=ids, is_visible=True, due_at__gte=now, due_at__lte=now + timedelta(days=days)).select_related("course"):
        if a.pk not in done:
            out.append({"kind": "a", "title": a.title, "course": a.course.code, "at": _local(a.due_at), "pk": a.pk})
    for q in Quiz.objects.filter(course_id__in=ids, is_visible=True, is_enabled=True, closes_at__gte=now, closes_at__lte=now + timedelta(days=days)).select_related("course"):
        out.append({"kind": "q", "title": q.title, "course": q.course.code, "at": _local(q.closes_at), "pk": q.pk})
    out.sort(key=lambda i: i["at"])
    return out


# ---------- iCalendar ----------

def _esc(text):
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _utc(dt):
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(user, days=120):
    """A plain .ics file of the next `days` days; text fields are escaped so titles cannot inject calendar lines."""
    today = timezone.localdate()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Lumen//Calendar//EN", "CALSCALE:GREGORIAN"]
    for n, it in enumerate(calendar_items(user, today, today + timedelta(days=days))):
        end = it["at"] + timedelta(hours=1)
        if it["kind"] == "c":
            slot = it["slot"]
            end = it["at"].replace(hour=slot.end_time.hour, minute=slot.end_time.minute, second=0)
        elif it["kind"] == "e" and it["event"].ends_at:
            end = it["event"].ends_at
        lines += ["BEGIN:VEVENT", f"UID:lumen-{user.pk}-{n}-{_utc(it['at'])}@lumen", f"DTSTAMP:{_utc(timezone.now())}",
                  f"DTSTART:{_utc(it['at'])}", f"DTEND:{_utc(end)}", f"SUMMARY:{_esc(it['title'])}", f"DESCRIPTION:{_esc(it['course'])}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
