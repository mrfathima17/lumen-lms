from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.uploads import serve_file
from apps.courses import permissions as perm
from apps.courses.models import Course
from apps.grading.models import GradeItem

from . import rubric, services
from .forms import AssignmentForm, CriterionForm, ExtensionForm, GradeForm, SubmissionForm
from .models import Assignment, Extension, RubricCriterion, Submission

User = get_user_model()


def _assignment_for_staff(request, pk):
    a = get_object_or_404(Assignment.objects.select_related("course"), pk=pk)
    if not perm.can_manage(request.user, a.course):
        raise PermissionDenied
    return a


@login_required
def overview(request):
    """Students: their assignments with status. Staff: assignments in their courses with marking counts."""
    user = request.user
    if user.role == "student":
        rows = []
        subs = {s.assignment_id: s for s in Submission.objects.filter(student=user)}
        for a in Assignment.objects.filter(is_visible=True, course__in=perm.visible_courses_for(user)).select_related("course"):
            s = subs.get(a.pk)
            due = services.effective_due(a, user)
            rows.append({"a": a, "s": s, "due": due, "overdue": s is None and due < timezone.now()})
        now = timezone.now()
        stats = {"week": sum(1 for r in rows if not r["s"] and now <= r["due"] <= now + timedelta(days=7)),
                 "submitted": sum(1 for r in rows if r["s"] and r["s"].status == "submitted"),
                 "graded": sum(1 for r in rows if r["s"] and r["s"].status == "graded"),
                 "overdue": sum(1 for r in rows if r["overdue"])}
        return render(request, "assignments/student_list.html", {"rows": rows, "stats": stats})
    assignments = Assignment.objects.filter(course__in=perm.visible_courses_for(user)).select_related("course")
    rows = []
    for a in assignments:
        total = a.course.enrolments.filter(status="active").count()
        got = a.submissions.count()
        rows.append({"a": a, "total": total, "got": got, "pending": a.submissions.filter(status="submitted").count()})
    now = timezone.now()
    stats = {"pending": sum(r["pending"] for r in rows), "graded": sum(r["got"] - r["pending"] for r in rows),
             "missing": sum(r["total"] - r["got"] for r in rows if r["a"].due_at < now),
             "late": Submission.objects.filter(assignment__in=[r["a"] for r in rows], late_days__gt=0).count()}
    subs = Submission.objects.filter(assignment__in=[r["a"] for r in rows]).select_related("student", "assignment__course").order_by("-submitted_at")
    pick, state = request.GET.get("assignment", ""), request.GET.get("status", "")
    if pick.isdigit():
        subs = subs.filter(assignment_id=int(pick))
    if state == "needs":
        subs = subs.filter(status="submitted")
    elif state == "graded":
        subs = subs.filter(status="graded")
    elif state == "late":
        subs = subs.filter(late_days__gt=0)
    return render(request, "assignments/staff_list.html", {"rows": rows, "stats": stats, "subs": list(subs[:100]), "pick": pick, "state": state})


@login_required
def detail(request, pk):
    a = get_object_or_404(Assignment.objects.select_related("course"), pk=pk)
    course = a.course
    manage = perm.can_manage(request.user, course)
    if not manage and not (a.is_visible and perm.can_view(request.user, course)):
        raise PermissionDenied
    item = GradeItem.objects.filter(assignment=a).first()
    ctx = {"a": a, "course": course, "manage": manage, "weight": item.weight if item else None}
    if manage:
        total = course.enrolments.filter(status="active").count()
        got = a.submissions.count()
        ctx["counts"] = {"total": total, "got": got, "pending": a.submissions.filter(status="submitted").count()}
        return render(request, "assignments/detail.html", ctx)
    sub = Submission.objects.filter(assignment=a, student=request.user).first()
    due = services.effective_due(a, request.user)
    form = None
    if not (sub and sub.status == "graded"):
        form = SubmissionForm(request.POST or None, request.FILES or None, assignment=a)
        if request.method == "POST" and form.is_valid():
            try:
                s = services.submit(a, request.user, form.cleaned_data["file"], form.cleaned_data["comment"])
            except services.SubmissionError as exc:
                messages.error(request, str(exc))
            else:
                audit.record(request, "assignment_submitted", target=course.code, detail=a.title)
                messages.success(request, "Your work was submitted late and will lose marks." if s.late_days else "Your work was submitted.")
                return redirect("assignments:detail", pk=a.pk)
    ctx.update({"scores": list(sub.rubric_scores.select_related("criterion")) if sub and sub.status == "graded" else [], "rubric_total": rubric.total_points(a),
                "sub": sub, "due": due, "form": form, "closed": due < timezone.now() and not a.allow_late, "overdue": due < timezone.now(),
                "rate": services.penalty_for(1)})
    return render(request, "assignments/detail.html", ctx)


@login_required
def edit(request, course_id=None, pk=None):
    if pk:
        a = _assignment_for_staff(request, pk)
        course = a.course
    else:
        a = None
        course = get_object_or_404(Course, pk=course_id)
        if not perm.can_manage(request.user, course):
            raise PermissionDenied
    form = AssignmentForm(request.POST or None, instance=a, course=course)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.course = course
        obj.save()
        audit.record(request, "assignment_saved", target=course.code, detail=obj.title)
        messages.success(request, "Assignment saved.")
        return redirect("assignments:detail", pk=obj.pk)
    return render(request, "assignments/form.html", {"form": form, "course": course, "a": a})


@login_required
def submissions(request, pk):
    a = _assignment_for_staff(request, pk)
    subs = {s.student_id: s for s in a.submissions.select_related("student")}
    now = timezone.now()
    rows = []
    for e in a.course.enrolments.filter(status="active").select_related("user"):
        sub, due = subs.get(e.user_id), services.effective_due(a, e.user)
        state = "graded" if sub and sub.status == "graded" else "needs" if sub else "missing" if due < now else "waiting"
        rows.append({"student": e.user, "s": sub, "due": due, "state": state})
    stats = {"needs": sum(r["state"] == "needs" for r in rows), "graded": sum(r["state"] == "graded" for r in rows),
             "missing": sum(r["state"] == "missing" for r in rows), "late": sum(1 for r in rows if r["s"] and r["s"].late_days)}
    only = request.GET.get("status", "")
    if only == "late":
        rows = [r for r in rows if r["s"] and r["s"].late_days]
    elif only in ("needs", "graded", "missing"):
        rows = [r for r in rows if r["state"] == only]
    return render(request, "assignments/submissions.html", {"a": a, "rows": rows, "now": now, "stats": stats, "only": only})


@login_required
def grade_view(request, sub_id):
    sub = get_object_or_404(Submission.objects.select_related("assignment__course", "student"), pk=sub_id)
    a = sub.assignment
    if not perm.can_manage(request.user, a.course):
        raise PermissionDenied
    penalty = services.penalty_for(sub.late_days)
    order = list(a.submissions.order_by("student__first_name", "student__last_name", "student__username", "pk").values_list("pk", flat=True))
    at = order.index(sub.pk)
    sub.prev_pk = order[at - 1] if at else None
    sub.next_pk = order[at + 1] if at + 1 < len(order) else None
    if rubric.has_rubric(a):
        return _grade_with_rubric(request, sub, a, penalty)
    initial = {"raw_mark": sub.raw_mark, "feedback": sub.feedback} if sub.raw_mark is not None else None
    form = GradeForm(request.POST or None, initial=initial, max_mark=a.max_mark)
    if request.method == "POST" and form.is_valid():
        services.grade(sub, form.cleaned_data["raw_mark"], form.cleaned_data["feedback"], request.user)
        audit.record(request, "submission_graded", target=a.course.code, detail=f"{a.title}: {sub.student.username}")
        messages.success(request, "Grade saved.")
        return _after_grade(request, sub, a)
    return render(request, "assignments/grade.html", {"form": form, "sub": sub, "a": a, "penalty": penalty})


def _after_grade(request, sub, a):
    if "save_next" in request.POST and sub.next_pk:
        return redirect("assignments:grade", sub_id=sub.next_pk)
    return redirect("assignments:submissions", pk=a.pk)


def _grade_with_rubric(request, sub, a, penalty):
    criteria = list(a.criteria.prefetch_related("levels"))
    saved = {s.criterion_id: s for s in sub.rubric_scores.all()}
    errors = ""
    chosen = {c.pk: (saved[c.pk].level_id if c.pk in saved else None, saved[c.pk].comment if c.pk in saved else "") for c in criteria}
    feedback = sub.feedback
    if request.method == "POST":
        feedback = request.POST.get("feedback", "")[:5000]
        for c in criteria:
            raw = request.POST.get(f"level{c.pk}", "")
            chosen[c.pk] = (int(raw) if raw.isdigit() else None, request.POST.get(f"comment{c.pk}", "").strip())
        try:
            rubric.grade(sub, chosen, feedback, request.user)
        except rubric.RubricError as exc:
            errors = str(exc)
        else:
            audit.record(request, "submission_graded", target=a.course.code, detail=f"{a.title}: {sub.student.username} (rubric)")
            messages.success(request, "Grade saved.")
            return _after_grade(request, sub, a)
    rows = [{"c": c, "levels": list(c.levels.all()), "level_id": chosen[c.pk][0], "comment": chosen[c.pk][1]} for c in criteria]
    return render(request, "assignments/grade_rubric.html", {"sub": sub, "a": a, "penalty": penalty, "rows": rows, "feedback": feedback, "error": errors, "total": rubric.total_points(a)})


@login_required
def submission_download(request, sub_id):
    sub = get_object_or_404(Submission.objects.select_related("assignment__course"), pk=sub_id)
    if sub.student_id != request.user.pk and not perm.can_manage(request.user, sub.assignment.course):
        raise PermissionDenied
    return serve_file(sub.file)


@login_required
def extensions_list(request):
    """Sidebar entry for staff: every assignment they can manage, with how many personal extensions it has."""
    if request.user.role == "student":
        raise PermissionDenied
    from django.db.models import Count

    rows = Assignment.objects.filter(course__in=perm.visible_courses_for(request.user)).select_related("course").annotate(n_ext=Count("extensions")).order_by("-due_at")
    now = timezone.now()
    return render(request, "assignments/extensions_list.html", {"rows": rows, "now": now})


@login_required
def extensions(request, pk):
    a = _assignment_for_staff(request, pk)
    form = ExtensionForm(request.POST or None, assignment=a)
    if request.method == "POST" and form.is_valid():
        Extension.objects.update_or_create(assignment=a, student=form.cleaned_data["student"],
                                           defaults={"due_at": form.cleaned_data["due_at"], "granted_by": request.user})
        audit.record(request, "extension_granted", target=a.course.code, detail=f"{a.title}: {form.cleaned_data['student'].username}")
        messages.success(request, "Extension saved.")
        return redirect("assignments:extensions", pk=a.pk)
    return render(request, "assignments/extensions.html", {"a": a, "form": form, "items": a.extensions.select_related("student")})


@require_POST
@login_required
def extension_delete(request, pk, ext_id):
    a = _assignment_for_staff(request, pk)
    ext = get_object_or_404(Extension, pk=ext_id, assignment=a)
    audit.record(request, "extension_removed", target=a.course.code, detail=f"{a.title}: {ext.student.username}")
    ext.delete()
    messages.success(request, "Extension removed.")
    return redirect("assignments:extensions", pk=a.pk)


# ---------------------------------------------------------------- rubric

@login_required
def rubric_editor(request, pk):
    a = _assignment_for_staff(request, pk)
    others = [o for o in Assignment.objects.filter(course=a.course).exclude(pk=a.pk) if rubric.has_rubric(o)]
    return render(request, "assignments/rubric.html", {
        "a": a, "criteria": a.criteria.prefetch_related("levels"), "total": rubric.total_points(a), "locked": rubric.is_locked(a), "others": others})


@login_required
def criterion_edit(request, pk=None, criterion_id=None):
    if criterion_id:
        crit = get_object_or_404(RubricCriterion.objects.select_related("assignment__course"), pk=criterion_id)
        a = crit.assignment
    else:
        crit, a = None, _assignment_for_staff(request, pk)
    if not perm.can_manage(request.user, a.course):
        raise PermissionDenied
    if rubric.is_locked(a):
        messages.error(request, "Work has already been marked with this rubric, so its rows are locked.")
        return redirect("assignments:rubric", pk=a.pk)
    if not crit and a.criteria.count() >= rubric.MAX_CRITERIA:
        messages.error(request, f"A rubric can have at most {rubric.MAX_CRITERIA} rows.")
        return redirect("assignments:rubric", pk=a.pk)
    initial = {"title": crit.title, "description": crit.description, "levels": rubric.levels_text(crit), "position": crit.position} if crit else None
    form = CriterionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        rubric.save_criterion(a, crit, d["title"], d["description"], form.parsed_levels, d["position"])
        audit.record(request, "rubric_saved", target=a.course.code, detail=a.title)
        messages.success(request, "Rubric row saved.")
        return redirect("assignments:rubric", pk=a.pk)
    return render(request, "assignments/criterion_form.html", {"form": form, "a": a, "crit": crit})


@require_POST
@login_required
def criterion_delete(request, criterion_id):
    crit = get_object_or_404(RubricCriterion.objects.select_related("assignment__course"), pk=criterion_id)
    a = crit.assignment
    if not perm.can_manage(request.user, a.course):
        raise PermissionDenied
    if rubric.is_locked(a):
        messages.error(request, "Work has already been marked with this rubric, so its rows are locked.")
    else:
        crit.delete()
        messages.success(request, "Row removed.")
    return redirect("assignments:rubric", pk=a.pk)


@require_POST
@login_required
def rubric_copy(request, pk):
    a = _assignment_for_staff(request, pk)
    src = Assignment.objects.filter(course=a.course, pk=request.POST.get("source") or 0).first()
    if not src or src.pk == a.pk or not rubric.has_rubric(src):
        messages.error(request, "Choose an assignment in this course that has a rubric.")
    elif rubric.has_rubric(a):
        messages.error(request, "This assignment already has a rubric. Remove its rows first.")
    else:
        n = rubric.copy_rubric(src, a)
        audit.record(request, "rubric_copied", target=a.course.code, detail=f"{src.title} to {a.title}")
        messages.success(request, f"Copied {n} row{'s' if n != 1 else ''} from {src.title}.")
    return redirect("assignments:rubric", pk=a.pk)
