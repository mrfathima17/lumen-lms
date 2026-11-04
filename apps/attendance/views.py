import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.core import audit
from apps.core.exports import safe_cell
from apps.courses import permissions as perm
from apps.courses.models import Course

from . import services
from .forms import SessionForm
from .models import AttendanceRecord, AttendanceSession


def _course_for_staff(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not perm.can_manage(request.user, course):
        raise PermissionDenied
    return course


def _session_for_staff(request, session_id):
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), pk=session_id)
    if not perm.can_manage(request.user, session.course):
        raise PermissionDenied
    return session


@login_required
def course_list(request):
    if request.user.role == "student":
        raise PermissionDenied
    return render(request, "attendance/course_list.html", {"courses": perm.visible_courses_for(request.user).select_related("semester")})


@login_required
def course_attendance(request, course_id):
    course = _course_for_staff(request, course_id)
    sessions = list(course.attendance_sessions.all())
    return render(request, "attendance/course.html", {
        "course": course, "sessions": sessions, "rows": services.course_overview(course), "limit": services.threshold(),
    })


@login_required
def session_new(request, course_id):
    course = _course_for_staff(request, course_id)
    form = SessionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.course, s.created_by = course, request.user
        s.save()
        return redirect("attendance:sheet", session_id=s.pk)
    return render(request, "attendance/session_form.html", {"form": form, "course": course})


@login_required
def sheet(request, session_id):
    session = _session_for_staff(request, session_id)
    course = session.course
    students = services.active_students(course)
    existing = dict(session.records.values_list("student_id", "status"))
    if request.method == "POST":
        posted = {}
        for s in students:
            posted[s.pk] = request.POST.get(f"status_{s.pk}", "")
        try:
            n = services.save_sheet(session, posted)
        except ValueError as e:
            messages.error(request, str(e))
            existing = {k: v for k, v in posted.items() if v in services.VALID} or existing
        else:
            audit.record(request, "attendance_saved", target=course.code, detail=f"{session.title} {session.held_on}")
            messages.success(request, f"Attendance saved for {n} student{'s' if n != 1 else ''}.")
            return redirect("attendance:sheet", session_id=session.pk)
    overall = {r["student"].pk: r for r in services.course_overview(course)}
    rows = [{"s": s, "status": existing.get(s.pk, ""), "overall": overall[s.pk]} for s in students]
    counts = services.stats(existing.values())
    return render(request, "attendance/sheet.html", {"session": session, "course": course, "rows": rows, "counts": counts,
                                                      "statuses": AttendanceRecord.Status.choices, "taken": bool(existing),
                                                      "all_sessions": list(course.attendance_sessions.order_by("-held_on", "-id")[:30])})


@require_POST
@login_required
def session_delete(request, session_id):
    session = _session_for_staff(request, session_id)
    course_id = session.course_id
    audit.record(request, "attendance_session_deleted", target=session.course.code, detail=f"{session.title} {session.held_on}")
    session.delete()
    messages.success(request, "Session deleted with its records.")
    return redirect("attendance:course", course_id=course_id)


@login_required
def export_csv(request, course_id):
    course = _course_for_staff(request, course_id)
    sessions = list(course.attendance_sessions.order_by("held_on", "id"))
    recs = {(sid, st): status for sid, st, status in AttendanceRecord.objects.filter(session__course=course).values_list("session_id", "student_id", "status")}
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{course.code}-attendance.csv"'
    w = csv.writer(resp)
    w.writerow(["Username", "Index number", "Name"] + [safe_cell(f"{s.title} {s.held_on:%Y-%m-%d}") for s in sessions] + ["Attended", "Counted", "Attendance %"])
    for r in services.course_overview(course):
        u, st = r["student"], r["stats"]
        w.writerow([safe_cell(u.username), safe_cell(u.index_number), safe_cell(u.get_full_name())]
                   + [recs.get((s.pk, u.pk), "") for s in sessions] + [st["attended"], st["counted"], "" if st["percent"] is None else st["percent"]])
    return resp


@role_required("student")
def my_attendance(request):
    limit = services.threshold()
    cards, total = [], []
    for c in perm.visible_courses_for(request.user).select_related("semester"):
        st = services.student_course_stats(c, request.user)
        total.append(st)
        cards.append({"course": c, "stats": st, "level": services.level(st["percent"], limit), "needed": services.sessions_needed(st, limit)})
    only = request.GET.get("course", "")
    recent = AttendanceRecord.objects.filter(student=request.user, session__course__in=[c["course"] for c in cards]).select_related("session", "session__course")
    if only.isdigit():
        recent = recent.filter(session__course_id=int(only))
    recent = recent.order_by("-session__held_on", "-session__id")[:40]
    overall = services.stats([s for st in total for s in ["present"] * st["present"] + ["late"] * st["late"] + ["absent"] * st["absent"] + ["excused"] * st["excused"]])
    return render(request, "attendance/my_attendance.html", {"cards": cards, "recent": recent, "overall": overall, "limit": limit, "only": only})
