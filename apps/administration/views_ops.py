"""Overview, reports, active sessions, backups and the roles page."""
import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.core import audit
from apps.core.exports import safe_cell
from apps.core.models import SiteSettings

from . import backups, reports, roles, sessions_admin
from .forms import BackupSettingsForm, MaintenanceForm

User = get_user_model()
admin_only = role_required("admin")


def overview_context():
    from apps.courses.models import Course

    week, week_total = reports.logins_last_week()
    return {
        "users": reports.user_counts(), "totals": reports.totals(), "attention": reports.attention(),
        "recent_signins": reports.recent_signins(), "recent_audit": reports.recent_audit(), "site": SiteSettings.load(),
        "total_users": User.objects.count(), "active_courses": Course.objects.filter(is_visible=True).count(),
        "online_now": reports.online_now(), "blocked_today": reports.blocked_today(), "week": week, "week_total": week_total, "health": reports.health(),
    }


@admin_only
def reports_page(request):
    weeks = reports.signups_by_week()
    top = max([w["count"] for w in weeks] + [1])
    for w in weeks:
        w["pct"] = round(100 * w["count"] / top)
    return render(request, "administration/reports.html", {
        "users": reports.user_counts(), "totals": reports.totals(), "rows": reports.course_rows(), "weeks": weeks, "days": reports.ACTIVE_DAYS,
    })


@admin_only
def reports_export(request):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="lumen-course-report.csv"'
    w = csv.writer(resp)
    w.writerow(["code", "title", "lecturers", "students", "assignments", "submissions", "quiz_attempts", "attendance_percent"])
    for r in reports.course_rows():
        c = r["course"]
        w.writerow([safe_cell(x) for x in (c.code, c.title, r["lecturers"], r["students"], r["assignments"], r["submissions"], r["attempts"], "" if r["attendance"] is None else r["attendance"])])
    audit.record(request, "report_exported", target="course report")
    return resp


# ---------------------------------------------------------------- sessions

@admin_only
def sessions_page(request):
    rows = sessions_admin.active_sessions()
    for r in rows:
        r["mine"] = r["key"] == request.session.session_key
    return render(request, "administration/sessions.html", {"rows": rows})


@require_POST
@admin_only
def session_end(request):
    key = request.POST.get("key", "")
    if key == request.session.session_key:
        messages.error(request, "That is your own session. Use Sign out in the top bar.")
    elif sessions_admin.end_session(key):
        audit.record(request, "session_ended", target="a session")
        messages.success(request, "Session ended. That person has to sign in again.")
    else:
        messages.error(request, "That session has already ended.")
    return redirect("administration:sessions")


@require_POST
@admin_only
def sessions_end_user(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    keep = request.session.session_key if user.pk == request.user.pk else None
    n = sessions_admin.end_user_sessions(user, keep_key=keep)
    audit.record(request, "sessions_ended", target=user.username, detail=f"{n} session(s)")
    messages.success(request, f"Signed {user.username} out of {n} session{'s' if n != 1 else ''}.")
    return redirect("administration:sessions")


# ---------------------------------------------------------------- backups

def _backups_page(request, backup_form=None, maint_form=None, status=200):
    site = SiteSettings.load()
    return render(request, "administration/backups.html", {
        "backups": backups.list_backups(), "site": site,
        "backup_form": backup_form or BackupSettingsForm(instance=site), "maint_form": maint_form or MaintenanceForm(instance=site),
    }, status=status)


@admin_only
def backups_page(request):
    return _backups_page(request)


@require_POST
@admin_only
def backup_settings(request):
    form = BackupSettingsForm(request.POST, instance=SiteSettings.load())
    if not form.is_valid():
        return _backups_page(request, backup_form=form)
    form.save()
    audit.record(request, "backup_settings_changed", detail=", ".join(form.changed_data))
    messages.success(request, "Backup settings saved.")
    return redirect("administration:backups")


@require_POST
@admin_only
def maintenance_save(request):
    form = MaintenanceForm(request.POST, instance=SiteSettings.load())
    if not form.is_valid():
        return _backups_page(request, maint_form=form)
    changed = form.changed_data
    form.save()
    if changed:
        audit.record(request, "maintenance_changed", detail=", ".join(changed))
    messages.success(request, "Maintenance settings saved.")
    return redirect("administration:backups")


@require_POST
@admin_only
def maintenance_preview(request):
    """Shows the maintenance page with the message as typed (not yet saved). Opens in a new tab."""
    msg = request.POST.get("maintenance_message", "")[:300]
    resp = render(request, "errors/maintenance.html", {"preview": True, "preview_message": msg})
    resp.status_code = 200
    return resp


@require_POST
@admin_only
def backup_restore(request, name):
    if request.POST.get("confirm", "").strip() != "RESTORE":
        messages.error(request, "Nothing was restored: type RESTORE to confirm.")
        return redirect("administration:backups")
    who = request.user.get_username()
    try:
        safety = backups.restore_backup(name)
    except backups.RestoreError as exc:
        messages.error(request, str(exc))
        return redirect("administration:backups")
    except Exception as exc:
        messages.error(request, f"The restore failed and no data was changed: {exc}")
        return redirect("administration:backups")
    # Sessions are not part of a backup, so everyone (including you) is signed out. The restored audit log is the backup's own.
    audit.record(request, "backup_restored", target=name, detail=f"previous state kept as {safety}", user=User.objects.filter(username=who).first())
    return redirect(reverse("accounts:login") + "?restored=1")


@require_POST
@admin_only
def backup_create(request):
    try:
        name = backups.create_backup()
    except Exception as exc:  # pragma: no cover - disk full, permissions
        messages.error(request, f"The backup could not be created: {exc}")
        return redirect("administration:backups")
    audit.record(request, "backup_created", target=name)
    messages.success(request, f"Backup created: {name}")
    return redirect("administration:backups")


@admin_only
def backup_download(request, name):
    path = backups.path_for(name)
    if not path:
        raise Http404
    audit.record(request, "backup_downloaded", target=name)
    return FileResponse(open(path, "rb"), as_attachment=True, filename=name)


@require_POST
@admin_only
def backup_delete(request, name):
    if backups.delete_backup(name):
        audit.record(request, "backup_deleted", target=name)
        messages.success(request, "Backup deleted.")
    else:
        messages.error(request, "That backup no longer exists.")
    return redirect("administration:backups")


# ---------------------------------------------------------------- roles

@admin_only
def roles_page(request):
    return render(request, "administration/roles.html", {"roles": roles.ROLES, "matrix": roles.MATRIX})
