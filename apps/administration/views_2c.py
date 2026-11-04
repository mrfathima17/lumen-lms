"""Module switches, custom profile fields, per-user activity and bulk enrolment."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import ProfileField
from apps.assignments.models import Submission
from apps.core import audit, modules
from apps.core.audit_text import describe
from apps.core.models import AuditLog, ModuleSetting
from apps.courses import services as course_services
from apps.courses.models import Enrolment
from apps.messaging.models import Message
from apps.quizzes.models import Attempt

from .forms import BulkEnrolForm, ProfileFieldForm

User = get_user_model()
admin_only = role_required("admin")


# ---------------------------------------------------------------- modules

@admin_only
def modules_page(request):
    off = modules.disabled_keys()
    if request.method == "POST":
        on = set(request.POST.getlist("enabled"))
        changed = []
        for key in modules.MODULES:
            want = key in on
            if want != (key not in off):
                ModuleSetting.objects.update_or_create(key=key, defaults={"enabled": want})
                changed.append(f"{key} {'on' if want else 'off'}")
        if changed:
            audit.record(request, "modules_changed", detail=", ".join(changed))
            messages.success(request, "Saved: " + ", ".join(changed) + ".")
        else:
            messages.info(request, "Nothing changed.")
        return redirect("administration:modules")
    rows = [{"key": k, "label": v[0], "desc": v[1], "on": k not in off} for k, v in modules.MODULES.items()]
    return render(request, "administration/modules.html", {"rows": rows})


# ---------------------------------------------------------------- profile fields

@admin_only
def profile_fields(request):
    form = ProfileFieldForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        f = form.save()
        audit.record(request, "profile_field_added", target=f.key)
        messages.success(request, "Field added.")
        return redirect("administration:profile-fields")
    return render(request, "administration/profile_fields.html", {"form": form, "fields": ProfileField.objects.annotate(n=Count("values"))})


@admin_only
def profile_field_edit(request, field_id):
    obj = get_object_or_404(ProfileField, pk=field_id)
    form = ProfileFieldForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request, "profile_field_updated", target=obj.key)
        messages.success(request, "Field saved.")
        return redirect("administration:profile-fields")
    return render(request, "administration/profile_field_form.html", {"form": form, "obj": obj})


@require_POST
@admin_only
def profile_field_delete(request, field_id):
    obj = get_object_or_404(ProfileField, pk=field_id)
    n = obj.values.count()
    obj.delete()
    audit.record(request, "profile_field_deleted", target=obj.key, detail=f"{n} stored value(s) removed")
    messages.success(request, f"Field deleted along with {n} stored value{'s' if n != 1 else ''}.")
    return redirect("administration:profile-fields")


# ---------------------------------------------------------------- activity

def activity_for(user, limit=100):
    """Merged, newest-first timeline of what a person did."""
    items = []
    for a in AuditLog.objects.filter(user=user)[:limit]:
        items.append({"when": a.created_at, "kind": "Audit", "text": describe(a), "extra": a.ip_address or ""})
    for s in Submission.objects.filter(student=user).select_related("assignment__course")[:limit]:
        items.append({"when": s.submitted_at, "kind": "Assignment", "text": f"Submitted {s.assignment.title} ({s.assignment.course.code})", "extra": f"{s.late_days} day(s) late" if s.late_days else ""})
    for t in Attempt.objects.filter(student=user).select_related("quiz__course")[:limit]:
        items.append({"when": t.started_at, "kind": "Quiz", "text": f"Attempt {t.number} of {t.quiz.title} ({t.quiz.course.code})", "extra": t.get_status_display()})
    for m in Message.objects.filter(sender=user)[:limit]:
        items.append({"when": m.created_at, "kind": "Message", "text": f"Sent a message: {m.subject}", "extra": ""})
    items.sort(key=lambda i: i["when"], reverse=True)
    return items[:limit]


@admin_only
def activity_index(request):
    q = (request.GET.get("q") or "").strip()
    qs = User.objects.order_by("-last_login", "username")
    if q:
        qs = qs.filter(username__icontains=q) | qs.filter(first_name__icontains=q) | qs.filter(last_name__icontains=q) | qs.filter(index_number__icontains=q)
    return render(request, "administration/activity_index.html", {"people": qs.distinct()[:50], "q": q})


@admin_only
def user_activity(request, user_id):
    obj = get_object_or_404(User, pk=user_id)
    since = timezone.now() - timedelta(days=30)
    summary = {
        "signins_30": AuditLog.objects.filter(user=obj, action="sign_in", created_at__gte=since).count(),
        "submissions": Submission.objects.filter(student=obj).count(),
        "attempts": Attempt.objects.filter(student=obj).count(),
        "courses": Enrolment.objects.filter(user=obj, status="active").count() + obj.teaching_courses.count(),
    }
    return render(request, "administration/user_activity.html", {"obj": obj, "summary": summary, "items": activity_for(obj)})


# ---------------------------------------------------------------- bulk enrolment

SHOWN = 100  # rows of "Currently enrolled" listed on the page; the course's Participants page has everyone


def _bulk_page(request, form, course):
    people = course_services.people_in(course) if course else []
    return render(request, "administration/bulk_enrolment.html", {"form": form, "course": course, "people": people[:SHOWN], "people_total": len(people),
                                                                  "cohort_counts": dict(form.cohort_counts)})


@admin_only
def bulk_enrolment(request):
    from apps.courses.models import Course

    if request.method == "POST":
        form = BulkEnrolForm(request.POST)
        if form.is_valid():
            course, role = form.cleaned_data["course"], form.cleaned_data["role"]
            res = course_services.enrol_users(course, role, form.cleaned_data["identifiers"], form.cleaned_data["cohort"])
            n, total = len(res["enrolled"]), len(res["enrolled"]) + len(res["already"]) + len(res["not_found"]) + len(res["wrong_role"])
            noun = "student" if role == "student" else "lecturer"
            audit.record(request, "bulk_enrol", target=course.code, detail=f"{n} enrolled of {total}" if role == "student" else f"{n} lecturer(s) added of {total}")
            if n:
                messages.success(request, f"Enrolled {n} student{'s' if n != 1 else ''} in {course.code}." if role == "student"
                                 else f"Added {n} lecturer{'s' if n != 1 else ''} to {course.code}.")
            if res["already"]:
                names = [u.username for u in res["already"]]
                messages.info(request, f"Already on {course.code}: " + (", ".join(names) if len(names) <= 10 else f"{len(names)} people") + ".")
            if res["not_found"]:
                messages.error(request, "Not found: " + ", ".join(res["not_found"]) + ".")
            if res["wrong_role"]:
                messages.error(request, f"Not {noun}s, so skipped: " + ", ".join(res["wrong_role"]) + ".")
            if not (n or res["already"] or res["not_found"] or res["wrong_role"]):
                messages.info(request, "Nobody to enrol.")
            return redirect(f"{request.path}?course={course.pk}")
        course = form.fields["course"].queryset.filter(pk=request.POST.get("course") or 0).first()
        return _bulk_page(request, form, course)
    chosen = Course.objects.filter(pk=request.GET.get("course") or 0).first() or Course.objects.order_by("code").first()
    form = BulkEnrolForm(initial={"course": chosen.pk if chosen else None, "role": request.GET.get("role", "student")})
    return _bulk_page(request, form, chosen)


@require_POST
@admin_only
def bulk_enrolment_remove(request):
    from apps.courses.models import Course

    course = get_object_or_404(Course, pk=request.POST.get("course") or 0)
    user = get_object_or_404(User, pk=request.POST.get("user") or 0)
    if request.POST.get("role") == "lecturer":
        course.lecturers.remove(user)
        detail = f"{user.username} (lecturer)"
    else:
        Enrolment.objects.filter(course=course, user=user).delete()
        detail = user.username
    audit.record(request, "unenrol", target=course.code, detail=detail)
    messages.success(request, f"Removed {user.get_full_name() or user.username} from {course.code}.")
    return redirect(f"{reverse('administration:bulk-enrolment')}?course={course.pk}")
