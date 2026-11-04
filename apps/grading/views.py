import csv
from decimal import Decimal, InvalidOperation

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
from .forms import GradeItemForm, WeightForm
from .models import GradeBand, GradeItem, ManualMark


def _course_for_staff(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not perm.can_manage(request.user, course):
        raise PermissionDenied
    return course


def _item_for_staff(request, item_id):
    item = get_object_or_404(GradeItem.objects.select_related("course"), pk=item_id)
    if not perm.can_manage(request.user, item.course):
        raise PermissionDenied
    return item


# ---------------------------------------------------------------- staff

@login_required
def gradebook_list(request):
    if request.user.role == "student":
        raise PermissionDenied
    courses = perm.visible_courses_for(request.user).select_related("semester")
    return render(request, "grading/gradebook_list.html", {"courses": courses})


def _matrix(course):
    items = list(course.grade_items.select_related("assignment", "quiz"))
    students = [e.user for e in course.enrolments.filter(status="active").select_related("user")]
    fr = services.load_fractions(course, [s.pk for s in students])
    rows = []
    for s in students:
        pct, gw, tw = services.course_percent(items, fr, s.pk)
        cells = [None if fr.get((i.pk, s.pk)) is None else services.q2(fr[(i.pk, s.pk)] * services.HUNDRED) for i in items]
        band = services.band_for(pct) if pct is not None else None
        rows.append({"student": s, "cells": cells, "percent": pct, "band": band})
    return items, rows


@login_required
def gradebook(request, course_id):
    course = _course_for_staff(request, course_id)
    items, rows = _matrix(course)
    total_weight = sum((i.weight for i in items), Decimal("0"))
    return render(request, "grading/gradebook.html", {
        "course": course, "items": items, "rows": rows, "total_weight": total_weight,
        "weight_ok": total_weight == 100, "published": course.results.count(),
    })


@login_required
def item_add(request, course_id):
    course = _course_for_staff(request, course_id)
    form = GradeItemForm(request.POST or None, course=course)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request, "grade_item_added", target=course.code, detail=form.cleaned_data["title"])
        messages.success(request, "Added to the gradebook.")
        return redirect("grading:gradebook", course_id=course.pk)
    return render(request, "grading/item_form.html", {"form": form, "course": course, "item": None})


@login_required
def item_edit(request, item_id):
    item = _item_for_staff(request, item_id)
    form = WeightForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("grading:gradebook", course_id=item.course_id)
    return render(request, "grading/item_form.html", {"form": form, "course": item.course, "item": item})


@require_POST
@login_required
def item_delete(request, item_id):
    item = _item_for_staff(request, item_id)
    course_id = item.course_id
    item.delete()
    messages.success(request, "Removed from the gradebook. The assignment or quiz itself is untouched.")
    return redirect("grading:gradebook", course_id=course_id)


@login_required
def manual_marks(request, item_id):
    item = _item_for_staff(request, item_id)
    if item.kind != GradeItem.Kind.MANUAL:
        raise PermissionDenied  # assignment and quiz marks come from their own marking screens
    students = [e.user for e in item.course.enrolments.filter(status="active").select_related("user")]
    existing = {m.student_id: m.mark for m in item.marks.all()}
    if request.method == "POST":
        parsed, errors = {}, []
        for s in students:
            raw = request.POST.get(f"mark_{s.pk}", "").strip()
            if raw == "":
                parsed[s.pk] = None
                continue
            try:
                m = Decimal(raw)
            except InvalidOperation:
                errors.append(f"{s.get_full_name() or s.username}: “{raw}” is not a number.")
                continue
            if m < 0 or m > item.max_mark:
                errors.append(f"{s.get_full_name() or s.username}: the mark must be between 0 and {item.max_mark:g}.")
                continue
            parsed[s.pk] = m
        if errors:
            for e in errors[:5]:
                messages.error(request, e)
            existing.update({k: v for k, v in parsed.items() if v is not None})
        else:
            for sid, m in parsed.items():
                if m is None:
                    ManualMark.objects.filter(item=item, student_id=sid).delete()
                else:
                    ManualMark.objects.update_or_create(item=item, student_id=sid, defaults={"mark": m})
            audit.record(request, "manual_marks_saved", target=item.course.code, detail=item.title)
            messages.success(request, "Marks saved.")
            return redirect("grading:gradebook", course_id=item.course_id)
    return render(request, "grading/manual_marks.html", {"item": item, "rows": [{"s": s, "mark": existing.get(s.pk)} for s in students]})


@require_POST
@login_required
def publish(request, course_id):
    course = _course_for_staff(request, course_id)
    count, skipped = services.publish_results(course, request.user)
    audit.record(request, "results_published", target=course.code, detail=f"{count} published, {len(skipped)} without marks")
    if count:
        messages.success(request, f"Published results for {count} student(s). They can now see them under Exam results.")
    if skipped:
        messages.info(request, f"No marks yet for: {', '.join(skipped)}.")
    if not count and not skipped:
        messages.error(request, "There are no enrolled students to publish.")
    return redirect("grading:gradebook", course_id=course.pk)


@login_required
def export_csv(request, course_id):
    course = _course_for_staff(request, course_id)
    items, rows = _matrix(course)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{course.code}-gradebook.csv"'
    w = csv.writer(resp)
    w.writerow(["Username", "Index number", "Name"] + [safe_cell(f"{i.title} ({i.weight:g}%)") for i in items] + ["Course %", "Letter"])
    for r in rows:
        s = r["student"]
        w.writerow([safe_cell(s.username), safe_cell(s.index_number), safe_cell(s.get_full_name())] + ["" if c is None else c for c in r["cells"]]
                   + ["" if r["percent"] is None else r["percent"], r["band"].letter if r["band"] else ""])
    return resp


# ---------------------------------------------------------------- student

@role_required("student")
def my_grades(request):
    courses = perm.visible_courses_for(request.user).prefetch_related("lecturers")
    summaries = [services.student_course_summary(c, request.user) for c in courses]
    marked = [s["percent"] for s in summaries if s["percent"] is not None]
    _, cumulative, _ = services.results_by_semester(request.user)
    stats = {"gpa": cumulative, "average": services.q2(sum(marked) / len(marked)) if marked else None,
             "graded": sum(s["graded"] for s in summaries), "pending": sum(s["pending"] for s in summaries)}
    return render(request, "grading/my_grades.html", {"summaries": summaries, "stats": stats})


@role_required("student")
def my_course_grades(request, course_id):
    course = get_object_or_404(perm.visible_courses_for(request.user), pk=course_id)
    return render(request, "grading/my_course_grades.html", {"course": course, "summary": services.student_course_summary(course, request.user)})


def _band_top(next_min):
    """The highest mark that still falls in the band below `next_min`: one whole mark lower, or 0.1 lower for a fractional boundary."""
    return next_min - (Decimal("1") if next_min == next_min.to_integral_value() else Decimal("0.1"))


STANDINGS = ((Decimal("3.5"), "ok", "Dean's list"), (Decimal("2.0"), "ok", "Good standing"), (Decimal("0"), "bad", "Academic warning"))


@role_required("student")
def my_results(request):
    semesters, cumulative, credits = services.results_by_semester(request.user)
    current = semesters[-1] if semesters else None
    pick = request.GET.get("semester", "")
    if pick.isdigit() and int(pick) < len(semesters):
        current = semesters[int(pick)]
    standing = None
    if current and current["gpa"] is not None:
        standing = next((tone, label) for floor, tone, label in STANDINGS if current["gpa"] >= floor)
    for i, sem in enumerate(semesters):
        sem["index"] = i
        sem["quality"] = sum((r.points * r.credits for r in sem["results"]), Decimal("0"))
        for r in sem["results"]:
            r.quality = r.points * r.credits
            r.tone = "ok" if r.points >= Decimal("3.3") else "warn" if r.points >= Decimal("2.0") else "bad"
        sem["bar"] = int((sem["gpa"] or 0) / Decimal("4") * 100)
    bands = list(GradeBand.objects.all())
    scale = [{"letter": b.letter, "points": b.points, "low": b.min_percent, "high": _band_top(bands[i - 1].min_percent) if i else Decimal("100")} for i, b in enumerate(bands)]
    return render(request, "grading/my_results.html", {"semesters": semesters, "current": current, "cumulative": cumulative, "credits": credits,
                                                       "standing": standing, "scale": scale, "student": request.user})
