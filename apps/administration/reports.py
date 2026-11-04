"""Numbers for the admin overview and the reports page. Everything is a read-only aggregate."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.attendance.models import AttendanceRecord
from apps.core.models import AuditLog, SiteSettings
from apps.courses.models import Course, Enrolment
from apps.quizzes.models import Attempt

User = get_user_model()
ACTIVE_DAYS = 30


def user_counts():
    by_role = {r: 0 for r, _ in User.Role.choices}
    for row in User.objects.filter(is_active=True).values("role").annotate(n=Count("id")):
        by_role[row["role"]] = row["n"]
    since = timezone.now() - timedelta(days=ACTIVE_DAYS)
    return {
        "by_role": by_role,
        "active_total": sum(by_role.values()),
        "disabled": User.objects.filter(is_active=False).count(),
        "signed_in_recently": User.objects.filter(is_active=True, last_login__gte=since).count(),
        "never_signed_in": User.objects.filter(is_active=True, last_login__isnull=True).count(),
        "must_change_password": User.objects.filter(is_active=True, must_change_password=True).count(),
    }


def attendance_percent():
    """Attended (present + late) over all marked records, excused left out. None when nothing is recorded."""
    c = AttendanceRecord.objects.aggregate(
        attended=Count("id", filter=Q(status__in=["present", "late"])),
        counted=Count("id", filter=~Q(status="excused")),
    )
    return round(100 * c["attended"] / c["counted"], 1) if c["counted"] else None


def totals():
    return {
        "courses": Course.objects.count(),
        "enrolments": Enrolment.objects.filter(status="active").count(),
        "assignments": Assignment.objects.count(),
        "submissions": Submission.objects.count(),
        "to_mark": Submission.objects.filter(status="submitted").count(),
        "attempts": Attempt.objects.exclude(status="in_progress").count(),
        "attendance_percent": attendance_percent(),
    }


def course_rows():
    """One row per course for the table and the CSV."""
    qs = (
        Course.objects.select_related("department", "semester").prefetch_related("lecturers")
        .annotate(
            students=Count("enrolments", filter=Q(enrolments__status="active"), distinct=True),
            assignment_count=Count("assignments", distinct=True),
            submission_count=Count("assignments__submissions", distinct=True),
        )
        .order_by("code")
    )
    rows = []
    for c in qs:
        recs = AttendanceRecord.objects.filter(session__course=c).aggregate(
            a=Count("id", filter=Q(status__in=["present", "late"])), n=Count("id", filter=~Q(status="excused"))
        )
        rows.append({
            "course": c,
            "lecturers": ", ".join(l.get_full_name() or l.username for l in c.lecturers.all()) or "—",
            "students": c.students,
            "assignments": c.assignment_count,
            "submissions": c.submission_count,
            "attempts": Attempt.objects.filter(quiz__course=c).exclude(status="in_progress").count(),
            "attendance": round(100 * recs["a"] / recs["n"], 1) if recs["n"] else None,
        })
    return rows


def signups_by_week(weeks=8):
    """New accounts per week for the last N weeks, oldest first."""
    today = timezone.localdate()
    start = today - timedelta(days=today.weekday())  # Monday of this week
    out = []
    for i in range(weeks - 1, -1, -1):
        a = start - timedelta(weeks=i)
        n = User.objects.filter(date_joined__date__gte=a, date_joined__date__lt=a + timedelta(days=7)).count()
        out.append({"week": a, "count": n})
    return out


def recent_signins(limit=6):
    return User.objects.filter(last_login__isnull=False).order_by("-last_login")[:limit]


def recent_audit(limit=6):
    return AuditLog.objects.select_related("user")[:limit]


def attention(request_ip_ok=True):
    """Things an administrator should look at, each as (level, text, url_name)."""
    from .backups import list_backups

    items = []
    s = SiteSettings.load()
    if s.maintenance_mode:
        items.append(("bad", "Maintenance mode is ON — students and lecturers see the maintenance page.", "administration:settings"))
    n = Submission.objects.filter(status="submitted").count()
    if n:
        items.append(("warn", f"{n} submission{'s' if n != 1 else ''} waiting to be marked.", None))
    pw = User.objects.filter(is_active=True, must_change_password=True).count()
    if pw:
        items.append(("warn", f"{pw} account{'s' if pw != 1 else ''} still on a sample password.", "administration:users"))
    from django.conf import settings

    if not settings.CELERY_TASK_ALWAYS_EAGER:
        from apps.core.models import JobHeartbeat

        beat = JobHeartbeat.objects.filter(name="scheduler").first()
        if beat is None or timezone.now() - beat.last_run > timedelta(minutes=5):
            items.append(("bad", "Background jobs are not running. Quiz attempts will not auto-submit and emails will not send until the worker and scheduler are started.", None))
    backups = list_backups()
    if not backups:
        items.append(("warn", "No backup has been made yet.", "administration:backups"))
    elif timezone.now() - backups[0]["created"] > timedelta(days=7):
        items.append(("warn", "The latest backup is more than 7 days old.", "administration:backups"))
    return items


def logins_last_week():
    """Sign-ins for each of the last seven days, oldest first, with a bar height in percent."""
    today = timezone.localdate()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    counts = {d: 0 for d in days}
    for row in AuditLog.objects.filter(action="sign_in", created_at__date__gte=days[0]).values_list("created_at", flat=True):
        d = timezone.localtime(row).date()
        if d in counts:
            counts[d] += 1
    top = max(counts.values()) or 1
    return [{"label": d.strftime("%a"), "count": n, "pct": max(round(100 * n / top), 3) if n else 3} for d, n in counts.items()], sum(counts.values())


def blocked_today():
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return AuditLog.objects.filter(action="ip_blocked", created_at__gte=start).count()


def online_now():
    from .sessions_admin import active_sessions

    return len({r["user"].pk for r in active_sessions() if r.get("user")})


def health():
    """A few honest checks of the server. Each item is (label, text, level) with level ok, warn or bad."""
    import shutil

    from django.conf import settings
    from django.db import connection

    from apps.core.models import JobHeartbeat

    from .backups import list_backups

    out = {}
    try:
        total, used, _ = shutil.disk_usage(settings.MEDIA_ROOT if settings.MEDIA_ROOT.exists() else settings.BASE_DIR)
        out["storage"] = round(100 * used / total)
    except OSError:
        out["storage"] = None
    try:
        connection.ensure_connection()
        out["database"] = ("Healthy", "ok")
    except Exception:  # noqa: BLE001 - any failure here means the database is not answering
        out["database"] = ("Not answering", "bad")
    backend = settings.EMAIL_BACKEND.lower()
    out["email"] = ("Not sending (test mode)", "warn") if ("console" in backend or "locmem" in backend or "dummy" in backend or "filebased" in backend) else ("Configured", "ok")
    if settings.CELERY_TASK_ALWAYS_EAGER:
        out["jobs"] = ("Run inline", "warn")
    else:
        beat = JobHeartbeat.objects.filter(name="scheduler").first()
        out["jobs"] = ("Running", "ok") if beat and timezone.now() - beat.last_run <= timedelta(minutes=5) else ("Not running", "bad")
    backups = list_backups()
    out["backup"] = backups[0]["created"] if backups else None
    return out
