import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.core import audit
from apps.core.exports import safe_cell
from apps.core.modules import disabled_keys
from apps.surveys import services as survey_services

from . import permissions as perm
from .forms import BulkEnrolForm, CategoryForm, CourseForm, CourseSettingsForm, GroupForm, SelfEnrolForm, TopicForm
from .models import Category, Course, Enrolment, Group, Topic
from .services import enrol_students, next_topic_position, parse_identifiers

User = get_user_model()


def _course_for_staff(request, pk):
    course = get_object_or_404(Course, pk=pk)
    if not perm.can_manage(request.user, course):
        raise PermissionDenied
    return course


# ---------- everyone: my courses, catalog, course page ----------

@login_required
def my_courses(request):
    # Re-query by id so the student count covers the whole class, not just the signed-in student's own enrolment row.
    ids = perm.visible_courses_for(request.user).values("pk")
    courses = Course.objects.filter(pk__in=ids).select_related("department", "semester").annotate(
        student_count=Count("enrolments", filter=Q(enrolments__status="active"))
    )
    courses = list(courses)
    if request.user.role == "student":
        from apps.completion import services as completion
        for c in courses:
            ev = completion.evaluate(c, request.user)
            c.progress = ev["percent"] if ev["tracked"] else None
    return render(request, "courses/my_courses.html", {"courses": courses})


@role_required("student")
def catalog(request):
    q = request.GET.get("q", "").strip()
    dept = request.GET.get("department", "")
    courses = Course.objects.filter(is_visible=True).select_related("department", "semester")
    if q:
        courses = courses.filter(Q(code__icontains=q) | Q(title__icontains=q))
    if dept.isdigit():
        courses = courses.filter(department_id=int(dept))
    mine = set(Enrolment.objects.filter(user=request.user).values_list("course_id", flat=True))
    return render(request, "courses/catalog.html", {
        "courses": courses, "mine": mine, "q": q, "dept": dept,
        "departments": Category.objects.filter(kind="department"),
    })


@login_required
def course_detail(request, pk):
    course = get_object_or_404(Course.objects.select_related("department", "semester"), pk=pk)
    if not perm.can_view(request.user, course):
        raise PermissionDenied
    manage = perm.can_manage(request.user, course)
    is_student = request.user.role == "student"
    topics = list(course.topics.all() if manage else course.topics.filter(is_visible=True))
    for t in topics:
        resources, tasks = t.resources.all(), t.assignments.all()
        if not manage:
            resources, tasks = resources.filter(is_visible=True), tasks.filter(is_visible=True)
        t.res, t.asg = list(resources), list(tasks)
    loose = course.assignments.filter(topic__isnull=True)
    if not manage:
        loose = loose.filter(is_visible=True)
    quizzes = course.quizzes.all() if manage else course.quizzes.filter(is_visible=True)
    ctx = {"course": course, "topics": topics, "manage": manage, "topic_form": TopicForm(), "tab": "content",
           "lecturers": course.lecturers.all(), "loose_assignments": loose, "quizzes": quizzes,
           "submitted": set(), "attempted": set(), "surveys": [], "progress": None}
    if "surveys" not in disabled_keys(request):
        surveys = course.surveys.all() if manage else course.surveys.filter(is_visible=True)
        ctx["surveys"] = [{"obj": sv, "state": survey_services.state(sv),
                           "answered": is_student and survey_services.has_answered(sv, request.user)} for sv in surveys]
    if is_student:
        from apps.assignments.models import Submission
        from apps.completion import services as completion
        from apps.quizzes.models import Attempt
        ctx["submitted"] = set(Submission.objects.filter(student=request.user, assignment__course=course).values_list("assignment_id", flat=True))
        ctx["attempted"] = set(Attempt.objects.filter(student=request.user, quiz__course=course).exclude(status="in_progress").values_list("quiz_id", flat=True))
        ctx["progress"] = completion.evaluate(course, request.user)
    return render(request, "courses/detail.html", ctx)


def _participant_rows(request, course, enrolments):
    """Each enrolment with the student's completion progress, grade and attendance, worked out in a few queries."""
    from apps.attendance import services as attendance
    from apps.completion import services as completion
    from apps.grading import services as grading

    rule = completion.rule_for(course)
    items = list(course.grade_items.all())
    fractions = grading.load_fractions(course, [e.user_id for e in enrolments])
    show_att = "attendance" not in disabled_keys(request)
    att = {r["student"].pk: r for r in attendance.course_overview(course)} if show_att else {}
    rows = []
    for e in enrolments:
        pct, _, _ = grading.course_percent(items, fractions, e.user_id)
        ev = completion.evaluate(course, e.user, rule)
        a = att.get(e.user_id)
        rows.append({"e": e, "grade": pct, "progress": ev["percent"] if ev["tracked"] else None,
                     "attendance": a["stats"]["percent"] if a else None})
    return rows


@login_required
def participants(request, pk):
    course = get_object_or_404(Course, pk=pk)
    if not perm.can_view(request.user, course):
        raise PermissionDenied
    manage = perm.can_manage(request.user, course)
    enrolments = list(course.enrolments.select_related("user").order_by("user__first_name", "user__last_name", "user__username"))
    rows = _participant_rows(request, course, enrolments) if manage else [{"e": e} for e in enrolments]
    staff_rows = []
    if not manage:
        from apps.accounts import people
        from apps.messaging.services import can_message

        for l in course.lecturers.all():
            staff_rows.append({"u": l, "email": l.email if people.can_see_email(request.user, l) else "", "can_message": request.user.pk != l.pk and can_message(request.user, l)})
        for r in rows:
            u = r["e"].user
            r["last"] = _ago_label(u.last_login) if u.pk != request.user.pk else "Now"
    if manage:
        from .reports import AT_RISK_BELOW

        for r in rows:
            r["last"] = _ago_label(r["e"].user.last_login)
            r["risk"] = r["e"].status == "active" and r["grade"] is not None and r["grade"] < AT_RISK_BELOW
    return render(request, "courses/participants.html", {
        "staff_rows": staff_rows,
        "course": course, "manage": manage, "lecturers": course.lecturers.all(), "tab": "participants",
        "rows": rows, "enrolments": enrolments, "form": BulkEnrolForm(),
        "show_attendance": manage and "attendance" not in disabled_keys(request),
    })


def _ago_label(when):
    if not when:
        return "Never"
    from django.utils import timezone

    days = (timezone.now().date() - timezone.localtime(when).date()).days
    return "Today" if days <= 0 else "Yesterday" if days == 1 else f"{days} days ago"


@login_required
def participants_export(request, pk):
    course = _course_for_staff(request, pk)
    enrolments = list(course.enrolments.select_related("user").order_by("user__first_name", "user__last_name", "user__username"))
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{course.code}-participants.csv"'
    w = csv.writer(response)
    w.writerow(["Name", "Username", "Index number", "Status", "Progress %", "Grade %", "Attendance %"])
    for r in _participant_rows(request, course, enrolments):
        u = r["e"].user
        w.writerow([safe_cell(u.get_full_name() or u.username), safe_cell(u.username), safe_cell(u.index_number or ""), r["e"].status,
                    "" if r["progress"] is None else r["progress"], "" if r["grade"] is None else r["grade"],
                    "" if r["attendance"] is None else r["attendance"]])
    return response


@role_required("student")
@require_POST
def self_enrol(request, pk):
    course = get_object_or_404(Course, pk=pk, is_visible=True)
    form = SelfEnrolForm(request.POST)
    if not course.allow_self_enrol:
        raise PermissionDenied
    if course.enrol_key and (not form.is_valid() or form.cleaned_data["key"] != course.enrol_key):
        messages.error(request, "That enrolment key is not correct.")
        return redirect("courses:catalog")
    _, created = Enrolment.objects.get_or_create(course=course, user=request.user)
    if created:
        audit.record(request, "self_enrol", target=course.code)
    messages.success(request, f"You are enrolled in {course.code}.")
    return redirect("courses:detail", pk=course.pk)


# ---------- staff: topics, enrolment, groups ----------

@require_POST
@login_required
def topic_add(request, pk):
    course = _course_for_staff(request, pk)
    form = TopicForm(request.POST)
    if form.is_valid():
        topic = form.save(commit=False)
        topic.course = course
        topic.position = next_topic_position(course)
        topic.save()
        messages.success(request, "Topic added.")
    else:
        messages.error(request, "A topic needs a title.")
    return redirect("courses:detail", pk=course.pk)


@require_POST
@login_required
def topic_action(request, pk, topic_id, action):
    course = _course_for_staff(request, pk)
    topic = get_object_or_404(Topic, pk=topic_id, course=course)
    if action == "toggle":
        topic.is_visible = not topic.is_visible
        topic.save(update_fields=["is_visible"])
    elif action == "delete":
        topic.delete()
        messages.success(request, "Topic deleted.")
    elif action in ("up", "down"):
        ordered = list(course.topics.all())
        i = next(n for n, t in enumerate(ordered) if t.pk == topic.pk)
        j = i - 1 if action == "up" else i + 1
        if 0 <= j < len(ordered):
            ordered[i], ordered[j] = ordered[j], ordered[i]
            for pos, t in enumerate(ordered):
                if t.position != pos:
                    Topic.objects.filter(pk=t.pk).update(position=pos)
    else:
        raise PermissionDenied
    return redirect("courses:detail", pk=course.pk)


@require_POST
@login_required
def bulk_enrol(request, pk):
    course = _course_for_staff(request, pk)
    form = BulkEnrolForm(request.POST)
    if form.is_valid():
        ids = parse_identifiers(form.cleaned_data["identifiers"])
        res = enrol_students(course, ids)
        audit.record(request, "bulk_enrol", target=course.code, detail=f"{len(res['enrolled'])} enrolled of {len(ids)}")
        if res["enrolled"]:
            messages.success(request, f"Enrolled {len(res['enrolled'])} student(s).")
        if res["already"]:
            messages.info(request, f"Already enrolled: {', '.join(res['already'])}.")
        if res["not_found"]:
            messages.error(request, f"Not found: {', '.join(res['not_found'])}.")
        if res["not_student"]:
            messages.error(request, f"Not students (only students can be enrolled): {', '.join(res['not_student'])}.")
    else:
        messages.error(request, "Enter at least one username or index number.")
    return redirect("courses:participants", pk=course.pk)


@require_POST
@login_required
def enrolment_action(request, pk, enrolment_id, action):
    course = _course_for_staff(request, pk)
    enrolment = get_object_or_404(Enrolment, pk=enrolment_id, course=course)
    if action == "remove":
        enrolment.delete()
        audit.record(request, "unenrol", target=course.code, detail=enrolment.user.username)
        messages.success(request, "Student removed from the course.")
    elif action == "suspend":
        enrolment.status = Enrolment.Status.SUSPENDED if enrolment.status == "active" else Enrolment.Status.ACTIVE
        enrolment.save(update_fields=["status"])
    else:
        raise PermissionDenied
    return redirect("courses:participants", pk=course.pk)


@login_required
def groups(request, pk):
    course = _course_for_staff(request, pk)
    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        g = form.save(commit=False)
        g.course = course
        if course.groups.filter(name__iexact=g.name).exists():
            messages.error(request, "A group with that name already exists.")
        else:
            g.save()
            messages.success(request, "Group created.")
        return redirect("courses:groups", pk=course.pk)
    return render(request, "courses/groups.html", {
        "course": course, "form": form,
        "groups": course.groups.prefetch_related("members"),
        "students": User.objects.filter(enrolments__course=course, enrolments__status="active").distinct(),
    })


@require_POST
@login_required
def group_member(request, pk, group_id, action):
    course = _course_for_staff(request, pk)
    group = get_object_or_404(Group, pk=group_id, course=course)
    user_id = request.POST.get("user", "")
    student = User.objects.filter(pk=user_id if user_id.isdigit() else 0, enrolments__course=course).first()
    if not student:
        messages.error(request, "Pick a student enrolled in this course.")
    elif action == "add":
        group.members.add(student)
    elif action == "remove":
        group.members.remove(student)
    else:
        raise PermissionDenied
    return redirect("courses:groups", pk=course.pk)


# ---------- admin: course and category management ----------

@role_required("admin")
def admin_courses(request):
    q = request.GET.get("q", "").strip()
    courses = Course.objects.select_related("department", "semester").prefetch_related("lecturers").annotate(student_count=Count("enrolments", distinct=True))
    if q:
        courses = courses.filter(Q(code__icontains=q) | Q(title__icontains=q))
    return render(request, "courses/admin_courses.html", {"courses": courses, "q": q})


@role_required("admin")
def admin_course_edit(request, pk=None):
    course = get_object_or_404(Course, pk=pk) if pk else None
    form = CourseForm(request.POST or None, instance=course)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        audit.record(request, "course_updated" if course else "course_created", target=saved.code)
        messages.success(request, "Course saved.")
        return redirect("courses:admin-courses")
    return render(request, "courses/admin_course_form.html", {"form": form, "course": course})


CATEGORY_KINDS = ("faculty", "department", "semester")


def _category_lists():
    today = timezone.localdate()
    semesters = list(Category.objects.filter(kind="semester").annotate(n=Count("semester_courses")))
    # Newest first; semesters without dates go last.
    semesters.sort(key=lambda s: (s.start_date is None, -(s.start_date or today).toordinal(), s.name))
    return {
        "faculties": Category.objects.filter(kind="faculty").annotate(n=Count("departments", distinct=True)),
        "departments": Category.objects.filter(kind="department").select_related("faculty").annotate(n=Count("department_courses")),
        "semesters": semesters,
    }


@role_required("admin")
def admin_categories(request):
    forms = {k: CategoryForm(initial={"kind": k}, auto_id=f"id_{k}_%s") for k in CATEGORY_KINDS}
    if request.method == "POST":
        data = request.POST.copy()
        if data.get("kind") not in CATEGORY_KINDS:
            data["kind"] = "department"  # an older form that sent no kind, or a bad value
        kind = data["kind"]
        form = CategoryForm(data, auto_id=f"id_{kind}_%s")
        if form.is_valid():
            saved = form.save()
            audit.record(request, "category_created", target=saved.name, detail=saved.kind)
            messages.success(request, f"{saved.get_kind_display()} \u201c{saved.name}\u201d added.")
            return redirect("courses:admin-categories")
        forms[kind] = form
    return render(request, "courses/admin_categories.html", {"forms": forms, **_category_lists()})


@role_required("admin")
def admin_category_edit(request, pk):
    cat = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=cat)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        audit.record(request, "category_updated", target=saved.name, detail=saved.kind)
        messages.success(request, f"{saved.get_kind_display()} saved.")
        return redirect("courses:admin-categories")
    usage = {"faculty": cat.departments.count(), "department": cat.department_courses.count(), "semester": cat.semester_courses.count()}[cat.kind]
    return render(request, "courses/admin_category_form.html", {"form": form, "cat": cat, "usage": usage})


@role_required("admin")
@require_POST
def admin_category_delete(request, pk):
    cat = get_object_or_404(Category, pk=pk)
    name, label = cat.name, cat.get_kind_display()
    audit.record(request, "category_deleted", target=name, detail=cat.kind)
    cat.delete()
    messages.success(request, f"{label} \u201c{name}\u201d deleted.")
    return redirect("courses:admin-categories")


# ---------- lecturer: course settings and reports ----------

@login_required
def course_settings(request, pk):
    course = _course_for_staff(request, pk)
    form = CourseSettingsForm(request.POST or None, instance=course)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request, "course_updated", target=course.code, detail="course settings")
        messages.success(request, "Settings saved.")
        return redirect("courses:settings", pk=course.pk)
    return render(request, "courses/settings.html", {"course": course, "form": form, "manage": True, "tab": "settings", "lecturers": course.lecturers.all()})


@login_required
def course_reports(request, pk):
    from . import reports

    course = _course_for_staff(request, pk)
    off = disabled_keys(request)
    data = reports.build(course, with_attendance="attendance" not in off, with_quizzes="quizzes" not in off)
    return render(request, "courses/reports.html", {"course": course, "manage": True, "tab": "reports", "lecturers": course.lecturers.all(), "r": data,
                                                    "show_attendance": "attendance" not in off, "show_quizzes": "quizzes" not in off})


TOOLS = {
    "students": ("Students", "Choose a course to see who is enrolled", "courses:participants", "users"),
    "reports": ("Course reports", "Choose a course to see grades, completion and activity", "courses:reports", "trending"),
    "settings": ("Course settings", "Choose a course to change its details and access", "courses:settings", "wrench"),
    "add-material": ("Add material", "Choose the course the file or link belongs to", "content:add", "upload"),
    "groups": ("Groups", "Choose a course to manage its groups", "courses:groups", "users"),
}


@role_required("lecturer", "admin")
def tool_list(request, tool):
    """The sidebar's course tools need a course: this lists the person's courses, or jumps straight in when there is only one."""
    from django.urls import reverse

    title, sub, url_name, icon = TOOLS[tool]
    courses = list(perm.visible_courses_for(request.user).order_by("code").select_related("semester"))
    if len(courses) == 1:
        return redirect(reverse(url_name, args=[courses[0].pk]))
    return render(request, "courses/tool_list.html", {"courses": courses, "title": title, "sub": sub, "url_name": url_name, "icon": icon})


# ---------- lecturer: view as student ----------

PREVIEW_PAGES = {
    "course": ("Course page", "courses:detail", True),
    "dashboard": ("Student dashboard", "accounts:student-dashboard", False),
    "assignments": ("Assignments", "assignments:overview", False),
    "quizzes": ("Quizzes", "quizzes:student-list", False),
    "grades": ("Course grades", "grading:my-course-grades", True),
}


@role_required("lecturer", "admin")
def preview(request):
    from django.urls import reverse

    courses = list(perm.visible_courses_for(request.user).order_by("code"))
    if request.method == "POST":
        course = next((c for c in courses if str(c.pk) == request.POST.get("course")), None)
        where = PREVIEW_PAGES.get(request.POST.get("where"), PREVIEW_PAGES["course"])
        if course is None:
            messages.error(request, "Choose one of your courses.")
            return redirect("courses:preview")
        request.session["preview_course"] = course.pk
        audit.record(request, "preview_started", target=course.code)
        return redirect(reverse(where[1], args=[course.pk]) if where[2] else reverse(where[1]))
    return render(request, "courses/preview.html", {"courses": courses, "pages": [(k, v[0]) for k, v in PREVIEW_PAGES.items()],
                                                    "chosen": request.GET.get("course", "")})


@require_POST
@login_required
def preview_exit(request):
    pid = request.session.pop("preview_course", None)
    if pid:
        audit.record(request, "preview_ended", target=str(Course.objects.filter(pk=pid).values_list("code", flat=True).first() or pid))
    return redirect("courses:preview")
