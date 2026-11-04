from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.contrib.auth import logout

from apps.core import audit
from apps.core.models import SiteSettings

from django.contrib.auth import get_user_model, login as auth_login
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django_otp import login as otp_login

from . import twofactor
from .decorators import role_required
from .forms import LumenPasswordChangeForm, SignInForm

PENDING = "pending_2fa"
PENDING_MINUTES = 5
MAX_TRIES = 5


def _apply_remember(request, remember):
    """Without "Remember me" the session ends when the browser closes; with it, the normal session length applies."""
    if not remember:
        request.session.set_expiry(0)


class SignInView(LoginView):
    template_name = "registration/login.html"
    authentication_form = SignInForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if twofactor.is_enabled(user):
            # Password was right, but nobody is signed in until the second step succeeds.
            self.request.session[PENDING] = {"uid": user.pk, "backend": getattr(user, "backend", ""), "at": timezone.now().timestamp(),
                                              "next": self.get_redirect_url(), "tries": 0, "remember": bool(self.request.POST.get("remember"))}
            return redirect("accounts:two-factor-verify")
        response = super().form_valid(form)
        _apply_remember(self.request, bool(self.request.POST.get("remember")))
        audit.record(self.request, "sign_in", target=user.username, user=user)
        return response


@require_POST
def sign_out(request):
    logout(request)  # sign-outs are not audited: they are not security-relevant and only add noise
    return redirect("core:public-home")


@login_required
def home(request):
    """Send each signed-in user to the dashboard for their role."""
    return redirect(request.user.home_url_name)


@login_required
def password_change(request):
    form = LumenPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        update_session_auth_hash(request, user)
        audit.record(request, "password_change", target=user.username)
        messages.success(request, "Your password was changed.")
        return redirect("accounts:home")
    forced = request.user.must_change_password
    if forced:
        form.fields["old_password"].label = "Temporary password"
        form.fields["old_password"].widget.attrs["placeholder"] = "From your welcome email"
        form.fields["new_password1"].label = "New password"
        form.fields["new_password2"].label = "Confirm new password"
    return render(request, "registration/password_force.html" if forced else "registration/password_change.html", {"form": form, "forced": forced})


@role_required("student")
def student_dashboard(request):
    from .dashboard_layout import layout_for
    from .dashboards import student_context

    ctx = student_context(request.user)
    ctx["blocks"] = [b for b in layout_for(request.user) if b["shown"]]
    return render(request, "dashboards/student.html", ctx)


@role_required("student")
def customise_dashboard(request):
    from . import dashboard_layout as dl

    if request.method == "POST":
        if "reset" in request.POST:
            request.user.dashboard_layout = {}
            request.user.save(update_fields=["dashboard_layout"])
            messages.success(request, "Your dashboard is back to the default layout.")
            return redirect("accounts:customise-dashboard")
        order = request.POST.getlist("order")
        shown = request.POST.getlist("show")
        mv = request.POST.get("move", "")
        if ":" in mv:
            bid, _, step = mv.partition(":")
            order = dl.move([i for i in dict.fromkeys(order) if i in dl.INFO] or list(dl.IDS), bid, -1 if step == "up" else 1)
        dl.save_layout(request.user, order, shown)
        if not mv:
            messages.success(request, "Your dashboard layout was saved.")
        return redirect("accounts:customise-dashboard")
    return render(request, "accounts/customise_dashboard.html", {"blocks": dl.layout_for(request.user)})


@role_required("lecturer")
def lecturer_dashboard(request):
    from .dashboards import lecturer_context

    return render(request, "dashboards/lecturer.html", lecturer_context(request.user))


@role_required("admin")
def admin_overview(request):
    from apps.administration.views_ops import overview_context

    return render(request, "dashboards/admin.html", overview_context())


# ---------------------------------------------------------------- profile

from django.http import Http404  # noqa: E402
from django.shortcuts import get_object_or_404  # noqa: E402

from . import people  # noqa: E402
from .forms import OwnProfileForm  # noqa: E402
from .models import ProfileValue, User  # noqa: E402
from .profile_fields import fields_for  # noqa: E402


def _custom_values(user):
    vals = {v.field_id: v.value for v in ProfileValue.objects.filter(user=user)}
    return [(f.label, vals[f.pk]) for f in fields_for(user.role) if vals.get(f.pk)]


@login_required
def profile(request):
    from apps.administration import sessions_admin
    from apps.core.models import AuditLog

    form = OwnProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request, "profile_updated", target=request.user.username)
        messages.success(request, "Your details were saved.")
        return redirect("accounts:profile")
    mine = [s for s in sessions_admin.active_sessions() if s["user_id"] == request.user.pk]
    return render(request, "accounts/profile.html", {
        "form": form, "custom": _custom_values(request.user), "courses": people.courses_of(request.user),
        "other_sessions": max(len(mine) - 1, 0), "two_factor": twofactor.is_enabled(request.user),
        "signins": AuditLog.objects.filter(user=request.user, action="sign_in")[:5],
    })


@require_POST
@login_required
def sign_out_others(request):
    from apps.administration import sessions_admin

    n = sessions_admin.end_user_sessions(request.user, keep_key=request.session.session_key)
    audit.record(request, "sign_out_others", target=request.user.username, detail=f"{n} session(s)")
    messages.success(request, f"Signed out of {n} other session{'s' if n != 1 else ''}.")
    return redirect("accounts:profile")


def _ago(when):
    from django.utils.timesince import timesince

    first = timesince(when).split(",")[0].replace("\xa0", " ")
    return "Just now" if first.startswith("0") else first + " ago"


def _student_progress(request, target, courses):
    """Marks, attendance, completion and recent activity for a student, shown only to staff who manage one of the courses."""
    if target.role != "student" or request.user.role not in ("lecturer", "admin"):
        return None
    from apps.attendance import services as attendance
    from apps.completion import services as completion
    from apps.core import audit_text
    from apps.core.models import AuditLog
    from apps.courses import permissions as perm
    from apps.grading import services as grading

    managed = [c for c in courses if perm.can_manage(request.user, c)]
    if not managed:
        return None
    pick = request.GET.get("course", "")
    course = next((c for c in managed if str(c.pk) == pick), managed[0])
    summary = grading.student_course_summary(course, target)
    att = attendance.student_course_stats(course, target)
    comp = completion.evaluate(course, target)
    last = AuditLog.objects.filter(user=target, action="sign_in").first()
    recent = [{"text": audit_text.describe(a), "when": audit_text.when(a.created_at)}
              for a in AuditLog.objects.filter(user=target, result="success").exclude(action__in=["sign_out", "sign_out_others"])[:6]]
    return {"course": course, "managed": managed, "summary": summary, "attendance": att, "completion": comp,
            "last_active_label": _ago(last.created_at) if last else "Never", "recent": recent}


@login_required
def person(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if not people.can_view_person(request.user, target):
        raise Http404  # do not reveal whether the account exists
    from apps.messaging.services import can_message

    courses = people.shared_courses(request.user, target)
    return render(request, "accounts/person.html", {
        "progress": _student_progress(request, target, courses),
        "target": target, "courses": courses, "show_email": people.can_see_email(request.user, target),
        "custom": _custom_values(target) if request.user.role == "admin" else [], "can_message": request.user.pk != target.pk and can_message(request.user, target),
    })


# ---------------------------------------------------------------- two-factor

def _pending(request):
    data = request.session.get(PENDING)
    if not data or timezone.now().timestamp() - data.get("at", 0) > PENDING_MINUTES * 60:
        request.session.pop(PENDING, None)
        return None, None
    user = get_user_model().objects.filter(pk=data["uid"], is_active=True).first()
    return data, user


def two_factor_verify(request):
    """Second sign-in step. Reached only after a correct password."""
    data, user = _pending(request)
    if not user:
        messages.error(request, "Your sign-in timed out. Enter your password again.")
        return redirect("accounts:login")
    error = ""
    if request.method == "POST":
        device = twofactor.verify(user, request.POST.get("token", ""))
        if device:
            request.session.pop(PENDING, None)
            auth_login(request, user, backend=data.get("backend") or None)
            otp_login(request, device)
            _apply_remember(request, data.get("remember", False))
            used_backup = device.__class__.__name__ == "StaticDevice"
            audit.record(request, "sign_in", target=user.username, user=user, detail="two-factor (backup code)" if used_backup else "two-factor")
            if used_backup:
                messages.info(request, f"You used a backup code. {twofactor.backup_codes_left(user)} left.")
            nxt = data.get("next") or ""
            if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(nxt)
            return redirect(user.home_url_name)
        data["tries"] = data.get("tries", 0) + 1
        request.session[PENDING] = data
        audit.record(request, "two_factor_failed", target=user.username, user=user, result="failed")
        if data["tries"] >= MAX_TRIES:
            request.session.pop(PENDING, None)
            messages.error(request, "Too many wrong codes. Enter your password again.")
            return redirect("accounts:login")
        error = "That code is not right. Check the code in your app and try again."
    return render(request, "registration/two_factor_verify.html", {"error": error, "username": user.username, "left": MAX_TRIES - data.get("tries", 0)})


@login_required
def two_factor_settings(request):
    user = request.user
    issuer = SiteSettings.load().site_name
    enabled = twofactor.is_enabled(user)
    setup = None
    pending = None if enabled else twofactor.pending_device(user)
    if pending:
        setup = {"qr": twofactor.qr_svg(pending, issuer), "secret": twofactor.secret_text(pending)}
    codes = request.session.pop("backup_codes", None) if request.method == "GET" else None
    return render(request, "accounts/two_factor.html", {
        "enabled": enabled, "setup": setup, "codes": codes, "required": twofactor.required_for(user),
        "left": twofactor.backup_codes_left(user) if enabled else 0,
    })


@require_POST
@login_required
def two_factor_start(request):
    if not twofactor.is_enabled(request.user):
        twofactor.start_setup(request.user)
    return redirect("accounts:two-factor")


@require_POST
@login_required
def two_factor_confirm(request):
    if twofactor.confirm_setup(request.user, request.POST.get("token", "")):
        device = twofactor.confirmed_device(request.user)
        otp_login(request, device)  # this session counts as verified
        request.session["backup_codes"] = twofactor.new_backup_codes(request.user)
        audit.record(request, "two_factor_enabled", target=request.user.username)
        messages.success(request, "Two-factor sign-in is on. Save your backup codes now.")
    else:
        messages.error(request, "That code did not match. Check the code in your app (it changes every 30 seconds) and try again.")
    return redirect("accounts:two-factor")


def _password_ok(request):
    return request.user.check_password(request.POST.get("password", ""))


@require_POST
@login_required
def two_factor_new_codes(request):
    if not twofactor.is_enabled(request.user):
        return redirect("accounts:two-factor")
    if not _password_ok(request):
        messages.error(request, "Your password was not right.")
        return redirect("accounts:two-factor")
    request.session["backup_codes"] = twofactor.new_backup_codes(request.user)
    audit.record(request, "two_factor_codes_renewed", target=request.user.username)
    return redirect("accounts:two-factor")


@require_POST
@login_required
def two_factor_disable(request):
    if twofactor.required_for(request.user):
        messages.error(request, "Your account must use two-factor sign-in, so it cannot be turned off.")
    elif not _password_ok(request):
        messages.error(request, "Your password was not right.")
    else:
        twofactor.disable(request.user)
        audit.record(request, "two_factor_disabled", target=request.user.username)
        messages.success(request, "Two-factor sign-in is off.")
    return redirect("accounts:two-factor")


# ---------------------------------------------------------------- search

@login_required
def search(request):
    from . import search as finder

    q = finder.clean_query(request.GET.get("q"))
    tab = request.GET.get("tab", "all")
    if tab not in dict(finder.TABS):
        tab = "all"
    results, counts = finder.search(request.user, q, tab)
    return render(request, "accounts/search.html", {
        "q": q, "tab": tab, "results": results, "counts": counts, "total": sum(counts.values()), "too_short": bool(q) and len(q) < finder.MIN_LENGTH,
        "tabs": [(key, label, counts.get(key)) for key, label in finder.TABS],
    })


# ---------------------------------------------------------------- forgot password

RESET_MAX_PER_HOUR = 5


def _throttled(request, identifier):
    from django.core.cache import cache

    from apps.core.audit import client_ip

    key = f"pwreset:{client_ip(request)}:{identifier.lower()[:80]}"
    n = cache.get(key, 0)
    if n >= RESET_MAX_PER_HOUR:
        return True
    cache.set(key, n + 1, 3600)
    return False


def forgot_password(request):
    """Ask for a reset link by username or email. The answer is the same whether or not an account matches."""
    from django.conf import settings as dj_settings
    from django.contrib.auth.tokens import default_token_generator
    from django.core.mail import send_mail
    from django.db.models import Q
    from django.urls import reverse
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    if request.user.is_authenticated:
        return redirect("accounts:home")
    sent = False
    if request.method == "POST":
        ident = (request.POST.get("identifier") or "").strip()[:150]
        sent = True
        if ident and not _throttled(request, ident):
            site = SiteSettings.load().site_name
            users = get_user_model().objects.filter(is_active=True).exclude(email="").filter(Q(username__iexact=ident) | Q(email__iexact=ident))[:3]
            for u in users:
                link = request.build_absolute_uri(reverse("accounts:password-reset-confirm", args=[urlsafe_base64_encode(force_bytes(u.pk)), default_token_generator.make_token(u)]))
                send_mail(f"Reset your {site} password",
                          f"Hello {u.get_full_name() or u.username},\n\nSomeone asked to reset the password for your {site} account ({u.username}).\n"
                          f"Open this link within 30 minutes to choose a new one:\n\n{link}\n\nIf this was not you, ignore this email: your password has not changed.\n\n— {site}",
                          dj_settings.DEFAULT_FROM_EMAIL, [u.email], fail_silently=True)
        audit.record(request, "password_reset_requested", target=ident)
    return render(request, "registration/forgot_password.html", {"sent": sent})


def password_reset_confirm(request, uidb64, token):
    from django.contrib.auth.forms import SetPasswordForm
    from django.contrib.auth.tokens import default_token_generator
    from django.contrib import messages as msg
    from django.utils.http import urlsafe_base64_decode

    User = get_user_model()
    try:
        user = User.objects.get(pk=urlsafe_base64_decode(uidb64).decode(), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError, UnicodeDecodeError):
        user = None
    if user is None or not default_token_generator.check_token(user, token):
        return render(request, "registration/reset_invalid.html", status=400)
    form = SetPasswordForm(user, request.POST or None)
    for f in form.fields.values():
        f.widget.attrs["autocomplete"] = "new-password"
    if request.method == "POST" and form.is_valid():
        form.save()
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        audit.record(request, "password_reset_done", target=user.username, user=user)
        msg.success(request, "Your password was changed. Sign in with it now.")
        return redirect("accounts:login")
    return render(request, "registration/reset_confirm.html", {"form": form})
