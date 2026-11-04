import os

from django.http import FileResponse, Http404
from django.shortcuts import redirect, render

from .models import SiteSettings


def public_home(request):
    if request.user.is_authenticated:
        return redirect("accounts:home")
    from django.contrib.auth import get_user_model
    from apps.courses.models import Course
    User = get_user_model()
    courses = list(Course.objects.filter(is_visible=True).select_related("department", "semester").prefetch_related("lecturers").order_by("code"))
    depts = sorted({c.department.name for c in courses if c.department})
    stats = {
        "courses": len(courses),
        "learners": User.objects.filter(role="student", is_active=True).count(),
        "lecturers": User.objects.filter(role="lecturer", is_active=True).count(),
        "departments": len(depts),
    }
    return render(request, "public_home.html", {"courses": courses, "depts": depts, "stats": stats})


def permission_denied(request, exception=None):
    return render(request, "errors/403.html", status=403)


def not_found(request, exception=None):
    return render(request, "errors/404.html", status=404)


def healthz(request):
    """For uptime monitors and Docker: 200 when the database answers, 503 when it does not. Says nothing else."""
    from django.db import connection
    from django.http import HttpResponse

    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        return HttpResponse("database unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


BRAND_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


def brand_asset(request, kind):
    """The logo and login background. Public on purpose (the sign-in page needs them); only ever the images an administrator set."""
    s = SiteSettings.load()
    f = {"logo": s.logo, "login-bg": s.login_bg_image}.get(kind)
    if not f:
        raise Http404
    ctype = BRAND_IMAGE_TYPES.get(os.path.splitext(f.name)[1].lower())
    if not ctype:
        raise Http404
    try:
        resp = FileResponse(f.open("rb"), content_type=ctype)
    except FileNotFoundError:
        raise Http404 from None
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "public, max-age=86400"  # the ?v= in the URL changes whenever the image does
    return resp


def _base(request):
    return "base.html" if request.user.is_authenticated else "public_base.html"


def terms(request):
    from .legal import SECTIONS
    tab = request.GET.get("tab", "terms")
    if tab not in SECTIONS:
        tab = "terms"
    title, sections = SECTIONS[tab]
    return render(request, "terms.html", {"base_tpl": _base(request), "tab": tab, "tabs": [(k, v[0]) for k, v in SECTIONS.items()],
                                          "title": title, "sections": sections})


def help_page(request):
    from django.contrib import messages
    from django.shortcuts import redirect

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        from django.contrib.auth import get_user_model
        from apps.messaging import services

        subject, body = request.POST.get("subject", "").strip(), request.POST.get("message", "").strip()
        if not subject or not body:
            messages.error(request, "Add a subject and a message so support knows how to help.")
        else:
            admins = get_user_model().objects.filter(role="admin", is_active=True).exclude(pk=request.user.pk)[:5]
            for a in admins:
                services.send_message(request.user, a, "[Support] " + subject, body)
            messages.success(request, "Your message was sent to the administrators. Replies arrive in your Messages.")
        return redirect("core:help")
    return render(request, "help.html", {"base_tpl": _base(request)})


def session_expired(request):
    return render(request, "session_expired.html")
