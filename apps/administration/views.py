import csv
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model

from apps.accounts.decorators import role_required
from apps.core import audit
from apps.core.exports import safe_cell
from apps.core.audit_text import CATEGORY_LABELS, category_q
from apps.core.models import AuditLog

from . import services
from apps.accounts import twofactor
from apps.accounts.profile_fields import ProfileValuesForm
from .forms import CsvUploadForm, ImportOptionsForm, UserForm

User = get_user_model()
admin_only = role_required("admin")


def _login_url(request):
    return request.build_absolute_uri(reverse("accounts:login"))


def _stash_credentials(request, items):
    """Sample passwords are shown once, on the next page, and then forgotten."""
    request.session["new_credentials"] = items


# ---------------------------------------------------------------- users

@admin_only
def users(request):
    qs = services.search_users(request.GET.get("q"), request.GET.get("role"), request.GET.get("status"))
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    qs_params = request.GET.copy()
    qs_params.pop("page", None)
    return render(request, "administration/users.html", {"page": page, "q": request.GET.get("q", ""), "role": request.GET.get("role", ""),
                                                         "status": request.GET.get("status", ""), "roles": User.Role.choices, "qs": qs_params.urlencode(),
                                                         "stats": {"students": User.objects.filter(role="student", is_active=True).count(),
                                                                   "lecturers": User.objects.filter(role="lecturer", is_active=True).count(),
                                                                   "admins": User.objects.filter(role="admin", is_active=True).count(),
                                                                   "pending": User.objects.filter(must_change_password=True, is_active=True).count()}})


@admin_only
def users_export(request):
    qs = services.search_users(request.GET.get("q"), request.GET.get("role"), request.GET.get("status"))
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="lumen-users.csv"'
    w = csv.writer(resp)
    from apps.accounts.models import ProfileField, ProfileValue

    pfields = list(ProfileField.objects.filter(is_active=True))
    w.writerow(["username", "first_name", "last_name", "email", "role", "index_number", "faculty", "active"] + [f.key for f in pfields])
    vals = {}
    for v in ProfileValue.objects.filter(field__in=pfields).values_list("user_id", "field_id", "value"):
        vals[(v[0], v[1])] = v[2]
    for u in qs:
        w.writerow([safe_cell(x) for x in (u.username, u.first_name, u.last_name, u.email, u.role, u.index_number or "", u.faculty)] + ["yes" if u.is_active else "no"] + [safe_cell(vals.get((u.pk, f.pk), "")) for f in pfields])
    return resp


@admin_only
def user_new(request):
    form = UserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = {k: v for k, v in form.cleaned_data.items()}
        user, password, emailed = services.create_user(data, _login_url(request))
        audit.record(request, "user_created", target=user.username, detail=f"role {user.role}")
        _stash_credentials(request, [{"username": user.username, "password": password, "emailed": emailed}])
        messages.success(request, "User created.")
        return redirect("administration:user-edit", user_id=user.pk)
    return render(request, "administration/user_form.html", {"form": form, "obj": None})


@admin_only
def user_edit(request, user_id):
    obj = get_object_or_404(User, pk=user_id)
    form = UserForm(request.POST or None, instance=obj)
    extra = ProfileValuesForm(obj, request.POST or None)
    if request.method == "POST" and form.is_valid() and extra.is_valid():
        services.check_can_change(request.user, obj, new_role=form.cleaned_data["role"])
        old_role = User.objects.get(pk=obj.pk).role
        form.save()
        if form.cleaned_data["role"] == old_role:  # custom fields belong to the role they were filled in for
            extra.save()
        audit.record(request, "user_updated", target=obj.username, detail=f"role {old_role} → {obj.role}" if old_role != obj.role else "")
        messages.success(request, "Changes saved.")
        return redirect("administration:user-edit", user_id=obj.pk)
    creds = request.session.pop("new_credentials", None) if request.method == "GET" else None
    activity = AuditLog.objects.filter(user=obj)[:30]
    return render(request, "administration/user_form.html", {"form": form, "obj": obj, "creds": creds, "activity": activity, "extra": extra, "two_factor": twofactor.is_enabled(obj), "is_self": obj.pk == request.user.pk,
                                                            "enrolments": obj.enrolments.select_related("course").order_by("course__code")})


@require_POST
@admin_only
def user_reset_password(request, user_id):
    obj = get_object_or_404(User, pk=user_id)
    password, emailed = services.reset_password(obj, _login_url(request))
    audit.record(request, "password_reset", target=obj.username)
    _stash_credentials(request, [{"username": obj.username, "password": password, "emailed": emailed}])
    messages.success(request, "A new sample password was generated. The user must change it at the next sign-in.")
    return redirect("administration:user-edit", user_id=obj.pk)


@require_POST
@admin_only
def user_two_factor_reset(request, user_id):
    """For someone who lost their phone and backup codes: remove their devices so they can sign in with the password and set it up again."""
    obj = get_object_or_404(User, pk=user_id)
    twofactor.disable(obj)
    audit.record(request, "two_factor_reset", target=obj.username)
    messages.success(request, f"Two-factor was reset for {obj.username}. They sign in with their password and can set it up again.")
    return redirect("administration:user-edit", user_id=obj.pk)


@require_POST
@admin_only
def user_toggle_active(request, user_id):
    obj = get_object_or_404(User, pk=user_id)
    new_state = not obj.is_active
    services.check_can_change(request.user, obj, new_active=new_state)
    obj.is_active = new_state
    obj.save(update_fields=["is_active"])
    audit.record(request, "user_enabled" if new_state else "user_disabled", target=obj.username)
    messages.success(request, "Account enabled." if new_state else "Account disabled. The user is signed out and cannot sign in.")
    return redirect("administration:user-edit", user_id=obj.pk)


# ---------------------------------------------------------------- bulk import

SHOWN_ROWS = 200  # rows listed in the preview; the counts and the error report cover every row


def _import_page(request, opts=None, text=None, filename="", notice="", file_error=""):
    """The one-page import: upload + options on the left, preview on the right. `text` (the CSV) turns the preview on."""
    opts = opts or ImportOptionsForm()
    preview = None
    if text is not None:
        default_role = opts.cleaned_data["default_role"] if opts.is_bound and opts.is_valid() else "student"
        rows = services.validate_rows(services.parse_csv(text)[0], default_role)
        bad = sum(1 for r in rows if r["errors"])
        preview = {"rows": rows[:SHOWN_ROWS], "total": len(rows), "ok": len(rows) - bad, "bad": bad, "shown_all": len(rows) <= SHOWN_ROWS,
                   "duplicates": sum(1 for r in rows if r["status"] == "duplicate"), "text": text, "filename": filename}
    return render(request, "administration/import.html", {"opts": opts, "preview": preview, "columns": services.COLUMNS, "notice": notice,
                                                          "file_error": file_error})


@admin_only
def import_users(request):
    if request.method != "POST":
        return _import_page(request)
    opts = ImportOptionsForm(request.POST)
    text, filename, file_error = None, "", ""
    if request.FILES.get("file"):
        form = CsvUploadForm(request.POST, request.FILES)
        if form.is_valid():
            raw = form.cleaned_data["file"].read()
            _, file_error = services.parse_csv(raw)
            if not file_error:
                text, filename = raw.decode("utf-8-sig"), form.cleaned_data["file"].name
        else:
            file_error = " ".join(form.errors["file"])
    elif request.POST.get("text"):  # an option changed: check the same file again
        text, filename = request.POST["text"], request.POST.get("filename", "")
        _, file_error = services.parse_csv(text)
        if file_error:
            text = None
    else:
        file_error = "Choose a CSV file first."
    return _import_page(request, opts, text, filename, file_error=file_error or "")


def _posted_csv(request):
    rows, error = services.parse_csv(request.POST.get("text", ""))
    return rows, error


@require_POST
@admin_only
def import_confirm(request):
    opts = ImportOptionsForm(request.POST)
    rows, error = _posted_csv(request)
    if error:
        messages.error(request, error)
        return redirect("administration:import")
    if not opts.is_valid():
        return _import_page(request, opts, request.POST["text"], request.POST.get("filename", ""))
    o = opts.cleaned_data
    rows = services.validate_rows(rows, o["default_role"])  # re-validated on the server: the hidden field is never trusted
    dupes = sum(1 for r in rows if r["status"] == "duplicate")
    if dupes and not o["skip_existing"]:
        return _import_page(request, opts, request.POST["text"], request.POST.get("filename", ""),
                            notice=f"Nothing was imported: {dupes} row{'s' if dupes != 1 else ''} already exist (or repeat in the file). "
                                   "Switch on \"Skip rows that already exist\", or fix the file.")
    created = services.import_rows(rows, _login_url(request), password=o["sample_password"] or None, send_email=o["send_email"], force_change=o["force_change"])
    skipped = sum(1 for r in rows if r["errors"])
    audit.record(request, "users_imported", detail=f"{len(created)} created, {skipped} skipped")
    _stash_credentials(request, [{"username": u.username, "password": pw, "emailed": em, "name": u.get_full_name()} for _, u, pw, em in created])
    return redirect("administration:import-result")


@require_POST
@admin_only
def import_errors(request):
    """The rows that cannot be imported, with the reason, as a CSV to fix and upload again."""
    rows, error = _posted_csv(request)
    if error:
        messages.error(request, error)
        return redirect("administration:import")
    opts = ImportOptionsForm(request.POST)
    role = opts.cleaned_data["default_role"] if opts.is_valid() else "student"
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="users-import-errors.csv"'
    resp.write("\ufeff")  # so Excel reads it as UTF-8
    w = csv.writer(resp)
    w.writerow(["line", *services.COLUMNS, "problem"])
    for r in services.validate_rows(rows, role):
        if r["errors"]:
            w.writerow([r["line"], *[safe_cell(r[c]) for c in services.COLUMNS], "; ".join(r["errors"])])
    return resp


@admin_only
def import_result(request):
    creds = request.session.pop("new_credentials", None)
    if creds is None:
        return redirect("administration:import")
    return render(request, "administration/import_result.html", {"creds": creds})


# ---------------------------------------------------------------- audit log

@admin_only
def audit_log(request):
    qs = _audit_filtered(request)
    page = Paginator(qs.order_by("-created_at", "-id"), 50).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "administration/audit.html", {"page": page, "q": request.GET.get("q", "").strip(), "category": request.GET.get("category", ""),
                                                         "who": request.GET.get("user", "").strip(), "since": request.GET.get("since", ""),
                                                         "categories": CATEGORY_LABELS, "qs": params.urlencode()})


@admin_only
def audit_export(request):
    """The audit log as a CSV, with whatever filters are on screen (newest first, at most 5,000 rows)."""
    from apps.core.audit_text import describe

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="audit-log.csv"'
    w = csv.writer(resp)
    w.writerow(["Time", "User", "Event", "IP address", "Result"])
    for a in _audit_filtered(request).order_by("-created_at", "-id")[:5000]:
        w.writerow([a.created_at.strftime("%Y-%m-%d %H:%M:%S"), safe_cell(a.user.username if a.user_id else a.target if a.action == "login_failed" else ""),
                    safe_cell(describe(a)), a.ip_address or "", a.result])
    audit.record(request, "audit_exported", detail=request.GET.urlencode()[:200])
    return resp


def _audit_filtered(request):
    qs = AuditLog.objects.select_related("user")
    q, category, who = request.GET.get("q", "").strip(), request.GET.get("category", ""), request.GET.get("user", "").strip()
    action, since = request.GET.get("action", ""), request.GET.get("since", "")  # `action` (a raw name) still works for old links
    if q:
        qs = qs.filter(Q(target__icontains=q) | Q(detail__icontains=q) | Q(action__icontains=q.replace(" ", "_")))
    if category and category_q(category) is not None:
        qs = qs.filter(category_q(category))
    if action:
        qs = qs.filter(action=action)
    if who:
        qs = qs.filter(Q(user__username__iexact=who) | Q(action="login_failed", target__iexact=who))
    if since:
        try:
            qs = qs.filter(created_at__date__gte=datetime.strptime(since, "%Y-%m-%d").date())
        except ValueError:
            pass
    return qs


# ---------------------------------------------------------------- part 2: access rules, settings, theme, email templates

from django.core.mail import send_mail  # noqa: E402
from django.db import transaction  # noqa: E402

from apps.core.models import COLOUR_PRESETS, FONT_CHOICES, LOGIN_BACKGROUNDS, AllowedNetwork, SiteSettings  # noqa: E402
from apps.core.network import client_ip, ip_allowed  # noqa: E402
from apps.grading.models import GradeBand  # noqa: E402

from . import email_templates  # noqa: E402
from .forms import EmailTemplateForm, GradeBandFormSet, RuleForm, SystemSettingsForm, ThemeForm  # noqa: E402
from .models import DEFAULTS, EmailTemplate  # noqa: E402


class _Lockout(Exception):
    pass


def _still_allowed(request):
    """True when this administrator could still reach the admin area and the whole site after the change."""
    ip = client_ip(request)
    return ip_allowed(ip, AllowedNetwork.Scope.ADMIN) and ip_allowed(ip, AllowedNetwork.Scope.ALL)


def _guarded(request, change):
    """Run a rule change; undo it if it would lock the current administrator out."""
    try:
        with transaction.atomic():
            change()
            if not _still_allowed(request):
                raise _Lockout
    except _Lockout:
        messages.error(request, f"Not saved: your own address ({client_ip(request)}) would no longer be allowed into the admin area, and you would be locked out.")
        return False
    return True


@admin_only
def access(request):
    form = RuleForm()
    if request.method == "POST":
        form = RuleForm(request.POST)
        if form.is_valid():
            rule = form.save(commit=False)
            if _guarded(request, rule.save):
                audit.record(request, "ip_rule_added", target=rule.cidr, detail=f"{rule.name} · {rule.scope}")
                messages.success(request, "Rule added.")
                return redirect("administration:access")
            form = RuleForm(request.POST)
    ip = client_ip(request)
    scopes = []
    for value, label in AllowedNetwork.Scope.choices:
        n = AllowedNetwork.objects.filter(scope=value, is_active=True).count()
        scopes.append({"label": label, "active": n, "restricted": n > 0, "mine_ok": ip_allowed(ip, value)})
    return render(request, "administration/access.html", {"form": form, "rules": AllowedNetwork.objects.all(), "my_ip": ip, "scopes": scopes,
                                                          "blocked": AuditLog.objects.filter(action="ip_blocked").select_related("user").order_by("-created_at", "-id")[:8]})


@require_POST
@admin_only
def rule_toggle(request, rule_id):
    rule = get_object_or_404(AllowedNetwork, pk=rule_id)

    def change():
        rule.is_active = not rule.is_active
        rule.save(update_fields=["is_active"])

    if _guarded(request, change):
        audit.record(request, "ip_rule_enabled" if rule.is_active else "ip_rule_disabled", target=rule.cidr)
        messages.success(request, "Rule updated.")
    return redirect("administration:access")


@require_POST
@admin_only
def rule_delete(request, rule_id):
    rule = get_object_or_404(AllowedNetwork, pk=rule_id)
    label = rule.cidr
    if _guarded(request, rule.delete):
        audit.record(request, "ip_rule_deleted", target=label)
        messages.success(request, "Rule deleted.")
    return redirect("administration:access")


@admin_only
def system_settings(request):
    obj = SiteSettings.load()
    form = SystemSettingsForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        changed = ", ".join(f"{f}" for f in form.changed_data)
        form.save()
        audit.record(request, "settings_changed", detail=changed)
        messages.success(request, "Settings saved.")
        return redirect("administration:settings")
    return render(request, "administration/settings.html", {"form": form})


@admin_only
def grade_scale(request):
    qs = GradeBand.objects.order_by("-min_percent")
    formset = GradeBandFormSet(request.POST or None, queryset=qs)
    if request.method == "POST" and formset.is_valid():
        formset.save()
        audit.record(request, "grade_scale_changed", detail=f"{GradeBand.objects.count()} rows")
        messages.success(request, "Grade scale saved. Results already published keep the grades they were published with until you publish them again.")
        return redirect("administration:grade-scale")
    return render(request, "administration/grade_scale.html", {"formset": formset})


@admin_only
def theme(request):
    obj = SiteSettings.load()
    form = ThemeForm(request.POST or None, instance=obj)
    if request.method == "POST":
        if "reset" in request.POST:
            obj.reset_branding()
            audit.record(request, "theme_reset")
            messages.success(request, "Branding reset to the defaults.")
            return redirect("administration:theme")
        if form.is_valid():
            form.save()
            audit.record(request, "theme_changed", detail=", ".join(form.changed_data))
            messages.success(request, "Theme saved. It now applies to every page for everyone.")
            return redirect("administration:theme")
    options = {"presets": COLOUR_PRESETS, "backgrounds": LOGIN_BACKGROUNDS, "fonts": [f for f, _ in FONT_CHOICES]}
    return render(request, "administration/theme.html", {"form": form, "options": options, "obj": obj})


@admin_only
def email_template_list(request):
    return email_template_edit(request, EmailTemplate.Key.choices[0][0])


def _template_rows():
    existing = {t.key: t for t in EmailTemplate.objects.all()}
    return [{"key": k, "label": label, "subject": (existing.get(k).subject if k in existing else DEFAULTS[k][0]), "custom": k in existing}
            for k, label in EmailTemplate.Key.choices]


@admin_only
def email_template_edit(request, key):
    if key not in DEFAULTS:
        raise PermissionDenied
    obj = EmailTemplate.objects.filter(key=key).first() or EmailTemplate(key=key, subject=DEFAULTS[key][0], body=DEFAULTS[key][1])
    form = EmailTemplateForm(request.POST or None, instance=obj)
    sample = {"name": "Alex Example", "username": "alex", "password": "Sample-Pass-123", "site": SiteSettings.load().site_name, "login_url": _login_url(request)}
    if request.method == "POST":
        if "reset" in request.POST:
            EmailTemplate.objects.filter(key=key).delete()
            audit.record(request, "email_template_reset", target=key)
            messages.success(request, "Template reset to the default text.")
            return redirect("administration:email-template", key=key)
        if form.is_valid():
            form.save()
            if "send_test" in request.POST:
                if request.user.email:
                    subject, body = email_templates.render(key, sample)
                    send_mail("[Test] " + subject, body, settings.DEFAULT_FROM_EMAIL, [request.user.email], fail_silently=True)
                    messages.success(request, f"Saved. A test email with sample values was sent to {request.user.email}.")
                else:
                    messages.error(request, "Saved, but your account has no email address to send the test to.")
            else:
                messages.success(request, "Template saved.")
            audit.record(request, "email_template_changed", target=key)
            return redirect("administration:email-template", key=key)
    preview_subject, preview_body = email_templates.render(key, sample) if not form.errors else ("", "")
    return render(request, "administration/email_template_form.html", {"form": form, "obj": obj, "label": dict(EmailTemplate.Key.choices)[key],
                                                                        "placeholders": email_templates.PLACEHOLDERS, "preview_subject": preview_subject, "preview_body": preview_body,
                                                                        "rows": _template_rows(), "key": key})
