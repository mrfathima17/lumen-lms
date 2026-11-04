from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.courses import permissions as perm
from apps.courses.models import Course

from . import services
from .forms import EventForm, SlotForm, TodoForm
from .models import Event, TimetableSlot, TodoItem


def _month(request):
    try:
        y, m = (int(x) for x in request.GET.get("month", "").split("-"))
        return date(y, m, 1)
    except (ValueError, TypeError):
        return timezone.localdate().replace(day=1)


@login_required
def calendar(request):
    first = _month(request)
    prev = (first - timedelta(days=1)).replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    days = services.month_grid(request.user, first.year, first.month)
    events = [it["event"] for d in days if not d["off"] for it in d["items"] if it["kind"] == "e"]
    for e in events:
        e.can_delete = e.owner_id == request.user.pk or bool(e.course_id and perm.can_manage(request.user, e.course))
    return render(request, "schedule/calendar.html", {
        "first": first, "days": days, "events": events,
        "prev": prev.strftime("%Y-%m"), "next": nxt.strftime("%Y-%m"), "today_month": timezone.localdate().strftime("%Y-%m"),
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "staff": request.user.role != "student",
    })


@login_required
def event_new(request):
    form = EventForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        ev = form.save(commit=False)
        ev.owner = request.user
        ev.save()
        messages.success(request, "Event added to the calendar.")
        return redirect(reverse("schedule:calendar") + f"?month={timezone.localtime(ev.starts_at):%Y-%m}")
    return render(request, "schedule/event_form.html", {"form": form})


@require_POST
@login_required
def event_delete(request, event_id):
    ev = get_object_or_404(Event.objects.select_related("course"), pk=event_id)
    if ev.owner_id != request.user.pk and not (ev.course_id and perm.can_manage(request.user, ev.course)):
        raise PermissionDenied
    ev.delete()
    messages.success(request, "Event deleted.")
    return redirect("schedule:calendar")


@login_required
def timetable(request):
    try:
        offset = int(request.GET.get("week", 0))
    except ValueError:
        offset = 0
    offset = max(-52, min(52, offset))
    ctx = services.timetable_grid(request.user, offset)
    ctx.update({"staff": request.user.role != "student", "week": offset})
    return render(request, "schedule/timetable.html", ctx)


@login_required
def export_ics(request):
    resp = HttpResponse(services.build_ics(request.user), content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="lumen-calendar.ics"'
    return resp


def _course_for_staff(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not perm.can_manage(request.user, course):
        raise PermissionDenied
    return course


@login_required
def course_timetable(request, course_id):
    course = _course_for_staff(request, course_id)
    form = SlotForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        slot = form.save(commit=False)
        slot.course = course
        slot.save()
        messages.success(request, "Class added to the timetable.")
        return redirect("schedule:course-timetable", course_id=course.pk)
    return render(request, "schedule/course_timetable.html", {"course": course, "form": form, "slots": course.timetable_slots.all()})


@require_POST
@login_required
def slot_delete(request, slot_id):
    slot = get_object_or_404(TimetableSlot.objects.select_related("course"), pk=slot_id)
    if not perm.can_manage(request.user, slot.course):
        raise PermissionDenied
    course_id = slot.course_id
    slot.delete()
    messages.success(request, "Class removed.")
    return redirect("schedule:course-timetable", course_id=course_id)


# ---------------------------------------------------------------- to-do

@login_required
def todo(request):
    today = timezone.localdate()
    mine = list(TodoItem.objects.filter(user=request.user))
    open_items = [t for t in mine if not t.done]
    done_items = sorted((t for t in mine if t.done), key=lambda t: t.done_at or t.created_at, reverse=True)[:20]
    deadlines = services.deadlines_for(request.user) if request.user.role == "student" else []
    week_end = today + timedelta(days=7)
    stats = {
        "week": sum(1 for t in open_items if t.due_date and today <= t.due_date <= week_end) + sum(1 for d in deadlines if d["at"].date() <= week_end),
        "overdue": sum(1 for t in open_items if t.due_date and t.due_date < today),
        "done": sum(1 for t in mine if t.done),
        "open": len(open_items),
    }
    coming = _coming_up(open_items, deadlines, today)
    return render(request, "schedule/todo.html", {"form": TodoForm(), "coming": coming, "done_items": done_items, "stats": stats, "today": today})


def _days_pill(due, today, kind="task"):
    days = (due - today).days
    if days < 0:
        return "bad", "Overdue"
    if days == 0:
        return "warn", "Today"
    if days == 1:
        return "warn", "Tomorrow"
    if kind == "q":
        return "ok", "Open"
    return ("warn" if days <= 3 else "mute"), f"{days} days"


def _coming_up(open_items, deadlines, today):
    """Personal tasks and course deadlines in one list, soonest first; tasks without a date go last."""
    rows = []
    for t in open_items:
        pill = _days_pill(t.due_date, today) if t.due_date else ("mute", "No date")
        rows.append({"kind": "task", "pk": t.pk, "title": t.title, "sub": "Personal" + (f" · {t.due_date.strftime('%a %d %b').replace(' 0', ' ')}" if t.due_date else ""),
                     "pill": pill, "sort": (0, t.due_date) if t.due_date else (1, today)})
    for d in deadlines:
        day = timezone.localtime(d["at"]).date()
        rows.append({"kind": d["kind"], "pk": d["pk"], "title": d["title"], "sub": f"{d['course']} · {timezone.localtime(d['at']).strftime('%a %d %b').replace(' 0', ' ')}",
                     "pill": _days_pill(day, today, d["kind"]), "sort": (0, day)})
    rows.sort(key=lambda r: r["sort"])
    return rows


@require_POST
@login_required
def todo_add(request):
    form = TodoForm(request.POST)
    if form.is_valid():
        t = form.save(commit=False)
        t.user = request.user
        t.save()
    else:
        messages.error(request, "Give the task a title (up to 200 characters).")
    return redirect("schedule:todo")


def _own_todo(request, todo_id):
    t = get_object_or_404(TodoItem, pk=todo_id)
    if t.user_id != request.user.pk:
        raise PermissionDenied
    return t


@require_POST
@login_required
def todo_toggle(request, todo_id):
    t = _own_todo(request, todo_id)
    t.done = not t.done
    t.done_at = timezone.now() if t.done else None
    t.save(update_fields=["done", "done_at"])
    return redirect("schedule:todo")


@require_POST
@login_required
def todo_delete(request, todo_id):
    _own_todo(request, todo_id).delete()
    return redirect("schedule:todo")
