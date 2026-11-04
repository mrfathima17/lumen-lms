import json
import zipfile
from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.administration import backups, reports, sessions_admin
from apps.administration.roles import MATRIX
from apps.core.models import AuditLog, SiteSettings


@pytest.fixture(autouse=True)
def backup_dir(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path / "backups"


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


ADMIN_PAGES = ["reports", "reports-export", "sessions", "backups", "roles"]


@pytest.mark.parametrize("name", ADMIN_PAGES)
def test_admin_pages_open_for_admin_only(admin_client, student, lecturer, name):
    assert admin_client.get(reverse(f"administration:{name}")).status_code == 200
    for who in (student, lecturer):
        c = Client()
        c.force_login(who)
        assert c.get(reverse(f"administration:{name}")).status_code == 403
    assert Client().get(reverse(f"administration:{name}")).status_code == 302


# ---------- reports / overview ----------

def test_counts_and_attendance_exclude_excused(enrolled, course, lecturer):
    from apps.attendance.models import AttendanceRecord, AttendanceSession

    for i, st in enumerate(["present", "late", "absent", "excused"]):
        s = AttendanceSession.objects.create(course=course, held_on=timezone.localdate() - timedelta(days=i), title=f"S{i}")
        AttendanceRecord.objects.create(session=s, student=enrolled, status=st)
    # 2 attended out of 3 counted (excused left out)
    assert reports.attendance_percent() == pytest.approx(66.7)
    u = reports.user_counts()
    assert u["by_role"]["student"] == 1 and u["by_role"]["lecturer"] == 1 and u["never_signed_in"] == 2
    row = reports.course_rows()[0]
    assert row["students"] == 1 and row["attendance"] == pytest.approx(66.7) and "Perera" in row["lecturers"]


def test_overview_and_reports_render_with_data(admin_client, enrolled):
    r = admin_client.get(reverse("accounts:admin-overview"))
    assert r.status_code == 200 and b"Total users" in r.content and b"No backup has been made yet" in r.content
    r = admin_client.get(reverse("administration:reports"))
    assert b"CS201" in r.content


def test_attention_flags_maintenance_and_old_backups(admin_client, settings):
    s = SiteSettings.load()
    s.maintenance_mode = True
    s.save()
    texts = [t for _, t, _ in reports.attention()]
    assert any("Maintenance mode is ON" in t for t in texts)
    name = backups.create_backup()
    import os
    old = timezone.now().timestamp() - 9 * 86400
    os.utime(backups.path_for(name), (old, old))
    assert any("more than 7 days old" in t for _, t, _ in reports.attention())


def test_report_csv_is_formula_safe(admin_client, course):
    course.title = "=HYPERLINK(\"http://x\")"
    course.save()
    body = admin_client.get(reverse("administration:reports-export")).content.decode()
    assert "'=HYPERLINK" in body and AuditLog.objects.filter(action="report_exported").exists()


# ---------- sessions ----------

def test_sessions_listed_and_ended(admin_client, student):
    other = Client()
    other.force_login(student)
    rows = sessions_admin.active_sessions()
    assert {r["user"].username for r in rows} == {"admin1", student.username}
    key = next(r["key"] for r in rows if r["user"] == student)
    r = admin_client.post(reverse("administration:session-end"), {"key": key})
    assert r.status_code == 302 and not Session.objects.filter(session_key=key).exists()
    assert other.get(reverse("accounts:student-dashboard")).status_code == 302  # signed out
    assert AuditLog.objects.filter(action="session_ended").exists()


def test_cannot_end_own_session_by_key(admin_client, admin_user):
    key = admin_client.session.session_key
    admin_client.post(reverse("administration:session-end"), {"key": key})
    assert Session.objects.filter(session_key=key).exists()


def test_sign_out_everywhere_spares_own_session(admin_client, admin_user, student):
    a, b = Client(), Client()
    a.force_login(student)
    b.force_login(student)
    admin_client.post(reverse("administration:sessions-end-user", args=[student.pk]))
    assert a.get(reverse("accounts:student-dashboard")).status_code == 302
    assert b.get(reverse("accounts:student-dashboard")).status_code == 302
    admin_client.post(reverse("administration:sessions-end-user", args=[admin_user.pk]))
    assert admin_client.get(reverse("accounts:admin-overview")).status_code == 200


def test_expired_sessions_not_listed(admin_client):
    Session.objects.update(expire_date=timezone.now() - timedelta(minutes=1))
    assert sessions_admin.active_sessions() == []


def test_sessions_need_post(admin_client):
    assert admin_client.get(reverse("administration:session-end")).status_code == 405


# ---------- backups ----------

def test_backup_contains_data_and_media(admin_client, student, settings):
    (settings.MEDIA_ROOT / "private").mkdir(parents=True)
    (settings.MEDIA_ROOT / "private" / "a.txt").write_text("hello")
    r = admin_client.post(reverse("administration:backup-create"))
    assert r.status_code == 302
    (b,) = backups.list_backups()
    with zipfile.ZipFile(backups.path_for(b["name"])) as z:
        names = z.namelist()
        assert {"data.json", "manifest.json", "media/private/a.txt"} <= set(names)
        data = json.loads(z.read("data.json"))
    assert any(o["model"] == "accounts.user" and o["fields"]["username"] == student.username for o in data)
    assert not any(o["model"] == "sessions.session" for o in data)
    assert AuditLog.objects.filter(action="backup_created").exists()


def test_backup_download_and_delete(admin_client):
    name = backups.create_backup()
    r = admin_client.get(reverse("administration:backup-download", args=[name]))
    assert r.status_code == 200 and "attachment" in r["Content-Disposition"]
    from django.core import signals
    from django.db import close_old_connections

    signals.request_finished.disconnect(close_old_connections)  # closing the response fires request_finished, which would drop the test's own MySQL connection
    try:
        r.close()
    finally:
        signals.request_finished.connect(close_old_connections)
    admin_client.post(reverse("administration:backup-delete", args=[name]))
    assert backups.list_backups() == []


@pytest.mark.parametrize("bad", ["../../etc/passwd", "lumen-backup-1.zip", "data.json", "lumen-backup-20260101-000000.zip.part", "..%2f..%2fsettings.py"])
def test_backup_names_are_validated(admin_client, bad):
    assert backups.path_for(bad) is None
    assert admin_client.get(f"/admin-panel/backups/{bad}/download/").status_code == 404


def test_unknown_but_wellformed_backup_is_404(admin_client):
    assert admin_client.get(reverse("administration:backup-download", args=["lumen-backup-20200101-000000.zip"])).status_code == 404


def test_make_backup_command_prunes(db, settings):
    d = backups.backup_dir()
    for n in ("20260101-000000", "20260102-000000", "20260103-000000"):
        (d / f"lumen-backup-{n}.zip").write_bytes(b"x")
    call_command("make_backup", keep=2)
    names = [b["name"] for b in backups.list_backups()]
    assert len(names) == 2 and "lumen-backup-20260101-000000.zip" not in names


def test_non_admin_cannot_create_or_download_backup(student, lecturer):
    name = backups.create_backup()
    for who in (student, lecturer):
        c = Client()
        c.force_login(who)
        assert c.post(reverse("administration:backup-create")).status_code == 403
        assert c.get(reverse("administration:backup-download", args=[name])).status_code == 403


# ---------- roles ----------

def test_roles_matrix_is_well_formed():
    assert all(len(row) == 5 for row in MATRIX)


def test_roles_matrix_matches_real_access(admin_client, student, lecturer):
    page = admin_client.get(reverse("administration:roles")).content
    assert b"Administrator" in page and b"Create and disable users" in page
    c = Client()
    c.force_login(lecturer)
    assert c.get(reverse("administration:users")).status_code == 403  # matrix says lecturers can't


def test_matrix_course_management_rows_match_real_access(admin_client, course, student, lecturer):
    """Admins manage every course; lecturers only their own; students none. The matrix says so, so check it."""
    names = ["attendance:course", "grading:gradebook"]
    other = Client()
    from apps.accounts.models import User
    stranger = User.objects.create_user("other", password="Pass-12345-xyz", role="lecturer")
    other.force_login(stranger)
    own, stu = Client(), Client()
    own.force_login(lecturer)
    stu.force_login(student)
    for n in names:
        url = reverse(n, args=[course.pk])
        assert admin_client.get(url).status_code == 200
        assert own.get(url).status_code == 200
        assert other.get(url).status_code in (403, 404)
        assert stu.get(url).status_code in (403, 404)
    assert admin_client.get(reverse("quizzes:manage-list")).status_code == 200
    assert stu.get(reverse("quizzes:manage-list")).status_code == 403
