from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.core import audit
from apps.core.models import SiteSettings
from apps.courses import permissions as perm
from apps.courses.models import Course

from . import pdf, services
from .forms import RuleForm
from .models import Certificate


# ---------------------------------------------------------------- student

@role_required("student")
def mine(request):
    rows = []
    for course in perm.visible_courses_for(request.user).order_by("code"):
        rule = services.rule_for(course)
        r = services.evaluate(course, request.user, rule)
        cert = services.award_if_complete(course, request.user, rule) if r["tracked"] else None
        rows.append({"course": course, "result": r, "certificate": cert})
    return render(request, "completion/mine.html", {"rows": rows})


@role_required("student")
def mine_course(request, course_id):
    course = get_object_or_404(perm.visible_courses_for(request.user), pk=course_id)
    rule = services.rule_for(course)
    result = services.evaluate(course, request.user, rule)
    cert = services.award_if_complete(course, request.user, rule) if result["tracked"] else None
    others = []
    for c in perm.visible_courses_for(request.user).exclude(pk=course.pk):
        ev = services.evaluate(c, request.user)
        if ev["tracked"]:
            others.append({"course": c, "percent": ev["percent"]})
    sections, done_n, total_n = services.activity_checklist(course, request.user) if request.user.role == "student" else ([], 0, 0)
    return render(request, "completion/mine_course.html", {"course": course, "result": result, "certificate": cert, "others": others,
                                                            "sections": sections, "act_done": done_n, "act_total": total_n})


@login_required
def certificates(request):
    if request.user.role != "student":
        raise PermissionDenied
    certs = Certificate.objects.filter(student=request.user).select_related("course")
    have = {c.course_id for c in certs}
    pending = []
    for c in perm.visible_courses_for(request.user).exclude(pk__in=have).order_by("code"):
        ev = services.evaluate(c, request.user)
        if ev["tracked"]:
            pending.append({"course": c, "percent": ev["percent"]})
    return render(request, "completion/certificates.html", {"certs": certs, "pending": pending})


def _cert_for_download(request, code):
    cert = get_object_or_404(Certificate.objects.select_related("course", "student"), code=code.upper())
    u = request.user
    if not (cert.student_id == u.pk or perm.can_manage(u, cert.course)):
        raise Http404
    return cert


@login_required
def certificate_pdf(request, code):
    cert = _cert_for_download(request, code)
    brand = SiteSettings.load().brand_color or "#4f46e5"
    data = pdf.build_pdf(cert, SiteSettings.load().site_name, request.build_absolute_uri(reverse("completion:verify", args=[cert.code])), brand)
    resp = HttpResponse(data, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="certificate-{cert.course_code}-{cert.code}.pdf"'
    return resp


def verify(request, code):
    """Public: anyone holding a certificate code can confirm it. Shows only name, course and date."""
    cert = Certificate.objects.filter(code=(code or "").strip().upper()).first()
    return render(request, "completion/verify.html", {"cert": cert, "code": code}, status=200 if cert else 404)


# ---------------------------------------------------------------- staff

def _course(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not perm.can_manage(request.user, course):
        raise PermissionDenied
    return course


@role_required("lecturer", "admin")
def manage_list(request):
    courses = perm.visible_courses_for(request.user).order_by("code")
    return render(request, "completion/manage_list.html", {"courses": courses})


@role_required("lecturer", "admin")
def manage(request, course_id):
    course = _course(request, course_id)
    rule = services.rule_for(course)
    form = RuleForm(request.POST or None, instance=rule)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request, "completion_rule_saved", target=course.code)
        messages.success(request, "Completion rules saved.")
        return redirect("completion:manage", course_id=course.pk)
    rows = services.roster(course)
    return render(request, "completion/manage.html", {
        "course": course, "form": form, "rows": rows, "rule": rule,
        "done": sum(1 for r in rows if r["result"]["complete"]), "pending": sum(1 for r in rows if r["result"]["complete"] and not r["certificate"]),
    })


@require_POST
@role_required("lecturer", "admin")
def issue_all(request, course_id):
    course = _course(request, course_id)
    n = services.issue_all(course)
    audit.record(request, "certificates_issued", target=course.code, detail=f"{n} issued")
    messages.success(request, f"Issued {n} certificate{'s' if n != 1 else ''}." if n else "Nobody new qualifies for a certificate.")
    return redirect("completion:manage", course_id=course.pk)


@require_POST
@role_required("lecturer", "admin")
def revoke(request, cert_id):
    cert = get_object_or_404(Certificate.objects.select_related("course"), pk=cert_id)
    if not perm.can_manage(request.user, cert.course):
        raise PermissionDenied
    services.revoke(cert)
    audit.record(request, "certificate_revoked", target=cert.code, detail=cert.student_name)
    messages.success(request, f"Certificate {cert.code} revoked. It will show as not valid when checked.")
    return redirect("completion:manage", course_id=cert.course_id)
