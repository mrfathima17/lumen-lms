from django.shortcuts import redirect
from django.urls import reverse

ALLOWED_PREFIXES = ("/static/", "/media/", "/sign-out/", "/sign-in/")


class ForcePasswordChangeMiddleware:
    """Users created by an admin with a sample password must set their own before doing anything else."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and getattr(user, "must_change_password", False):
            change_url = reverse("accounts:password-change")
            if request.path != change_url and not request.path.startswith(ALLOWED_PREFIXES):
                return redirect(change_url)
        return self.get_response(request)


class TwoFactorRequiredMiddleware:
    """When the site requires two-factor for someone's role, they must set it up before using anything else."""

    ALLOWED = ("/static/", "/media/", "/sign-out/", "/sign-in/", "/profile/two-factor/", "/password/change/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and not request.path.startswith(self.ALLOWED):
            from . import twofactor

            if twofactor.required_for(user) and not twofactor.is_enabled(user):
                return redirect("accounts:two-factor")
        return self.get_response(request)


class PreviewMiddleware:
    """"View as student": a lecturer or admin who started a preview sees one course the way an enrolled student does.

    For the length of the request the in-memory user acts as a student of that course, the database row is never touched
    (save is switched off), and anything that would write (POST and friends) is refused, so nothing is recorded as the
    student's work. The preview pages themselves, sign-out and static files are left alone.
    """

    SAFE = ("GET", "HEAD", "OPTIONS")
    EXEMPT = ("/static/", "/media/", "/sign-out/", "/preview/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        pid = request.session.get("preview_course") if hasattr(request, "session") else None
        user = getattr(request, "user", None)
        if pid and user is not None and user.is_authenticated and not request.path.startswith(self.EXEMPT):
            from apps.courses import permissions as perm
            from apps.courses.models import Course

            course = Course.objects.filter(pk=pid).first() if user.role in ("lecturer", "admin") else None
            if course is None or not perm.can_manage(user, course):
                request.session.pop("preview_course", None)
            else:
                if request.method not in self.SAFE:
                    from django.contrib import messages
                    from django.utils.http import url_has_allowed_host_and_scheme

                    messages.info(request, "You are previewing as a student, so nothing was saved.")
                    back = request.META.get("HTTP_REFERER", "")
                    ok = url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()})
                    return redirect(back if ok else reverse("courses:detail", args=[course.pk]))
                user.real_role = user.role
                user.role = "student"
                user.preview_course_id = course.pk
                user.save = lambda *a, **k: None  # the preview must never write the real account
        return self.get_response(request)
