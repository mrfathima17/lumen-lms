import json
import zipfile
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.administration import backups
from apps.core.models import AuditLog, SiteSettings


@pytest.fixture(autouse=True)
def dirs(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path / "backups"
    settings.MEDIA_ROOT = tmp_path / "media"
    return tmp_path


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def local_input(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")


# ---------- page ----------

def test_page_has_both_cards_and_no_old_bits(admin_client):
    html = admin_client.get(reverse("administration:backups")).content.decode()
    for text in ("Protect your data and schedule downtime", "Automatic daily backup", "Backup time", "Keep backups for (days)", "Back up now",
                 "Enable maintenance mode", "Message to users", "Scheduled for", "Preview maintenance page", "No backups yet"):
        assert text in html, text
    for gone in ("A backup is one zip with every record", "contain password hashes", "Change in system settings", "Create backup now"):
        assert gone not in html, gone
    assert 'type="time"' in html and 'type="datetime-local"' in html and 'value="02:00"' in html


def test_backup_list_shows_restore_download_delete(admin_client):
    name = backups.create_backup()
    html = admin_client.get(reverse("administration:backups")).content.decode()
    assert name in html and "data-restore" in html and reverse("administration:backup-download", args=[name]) in html and reverse("administration:backup-delete", args=[name]) in html


# ---------- backup settings ----------

def test_backup_settings_saved_and_audited(admin_client):
    r = admin_client.post(reverse("administration:backup-settings"), {"backup_time": "03:30", "backup_keep_days": "14"})  # toggle unchecked = off
    assert r.status_code == 302
    s = SiteSettings.load()
    assert (s.backup_auto, s.backup_time.strftime("%H:%M"), s.backup_keep_days) == (False, "03:30", 14)
    assert "backup_auto" in AuditLog.objects.get(action="backup_settings_changed").detail
    assert 'value="03:30"' in admin_client.get(reverse("administration:backups")).content.decode()


@pytest.mark.parametrize("data", [{"backup_time": "25:99", "backup_keep_days": "14"}, {"backup_time": "02:00", "backup_keep_days": "0"},
                                  {"backup_time": "02:00", "backup_keep_days": "99999"}, {"backup_time": "02:00", "backup_keep_days": "abc"}, {"backup_keep_days": "5"}])
def test_bad_backup_settings_refused(admin_client, data):
    r = admin_client.post(reverse("administration:backup-settings"), {"backup_auto": "on", **data})
    assert r.status_code == 200 and SiteSettings.load().backup_keep_days == 30


# ---------- automatic backups ----------

def at(h, m=0, days=0):
    return (timezone.localtime().replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=days))


def test_automatic_backup_runs_once_after_the_chosen_time(db):
    SiteSettings.objects.filter(pk=1).update(backup_auto=True, backup_time="02:00")
    SiteSettings.load()
    assert backups.run_scheduled(now=at(1, 59)) is None
    first = backups.run_scheduled(now=at(2, 5))
    assert first and backups.run_scheduled(now=at(2, 10)) is None and backups.run_scheduled(now=at(23, 0)) is None
    assert len(backups.list_backups()) == 1


def test_automatic_backup_off_does_nothing(db):
    SiteSettings.load(); SiteSettings.objects.filter(pk=1).update(backup_auto=False)
    assert backups.run_scheduled(now=at(23, 0)) is None and backups.list_backups() == []


def test_prune_by_days_keeps_the_newest(db):
    import os
    names = []
    for i, age in enumerate((40, 35, 3)):
        n = f"lumen-backup-2026010{i + 1}-000000.zip"
        (backups.backup_dir() / n).write_bytes(b"x")
        t = (timezone.now() - timedelta(days=age)).timestamp()
        os.utime(backups.backup_dir() / n, (t, t)); names.append(n)
    assert backups.prune_older_than(30) == 2
    assert [b["name"] for b in backups.list_backups()] == [names[2]]
    # even when everything is old, the newest backup is never deleted
    t = (timezone.now() - timedelta(days=99)).timestamp(); os.utime(backups.backup_dir() / names[2], (t, t))
    assert backups.prune_older_than(30) == 0 and len(backups.list_backups()) == 1


# ---------- maintenance ----------

def test_maintenance_saved_with_schedule_and_audited(admin_client):
    when = timezone.now() + timedelta(hours=5)
    r = admin_client.post(reverse("administration:maintenance-save"), {"maintenance_message": "Back at 9", "maintenance_at": local_input(when)})
    assert r.status_code == 302
    s = SiteSettings.load()
    assert not s.maintenance_mode and s.maintenance_message == "Back at 9" and abs((s.maintenance_at - when).total_seconds()) < 61
    assert AuditLog.objects.filter(action="maintenance_changed").exists()
    assert local_input(when) in admin_client.get(reverse("administration:backups")).content.decode()


def test_schedule_in_the_past_refused(admin_client):
    r = admin_client.post(reverse("administration:maintenance-save"), {"maintenance_message": "x", "maintenance_at": local_input(timezone.now() - timedelta(hours=1))})
    assert r.status_code == 200 and SiteSettings.load().maintenance_at is None and b"Choose a time in the future" in r.content


def test_scheduled_maintenance_switches_on_by_itself(client, student, admin_user, db):
    SiteSettings.load()
    SiteSettings.objects.filter(pk=1).update(maintenance_at=timezone.now() - timedelta(minutes=1), maintenance_mode=False)
    client.force_login(student)
    assert client.get(reverse("accounts:student-dashboard")).status_code == 503
    s = SiteSettings.load()
    assert s.maintenance_mode and s.maintenance_at is None
    assert AuditLog.objects.get(action="maintenance_changed").detail == "switched on as scheduled"
    client.force_login(admin_user)
    assert client.get(reverse("administration:backups")).status_code == 200  # admins still get in


def test_users_see_a_notice_before_maintenance_starts(client, student, db):
    SiteSettings.load()
    SiteSettings.objects.filter(pk=1).update(maintenance_at=timezone.now() + timedelta(hours=3))
    client.force_login(student)
    assert b"Scheduled maintenance" in client.get(reverse("accounts:student-dashboard")).content
    SiteSettings.objects.filter(pk=1).update(maintenance_at=timezone.now() + timedelta(days=9))
    assert b"Scheduled maintenance" not in client.get(reverse("accounts:student-dashboard")).content


def test_preview_uses_the_typed_message_and_changes_nothing(admin_client):
    r = admin_client.post(reverse("administration:maintenance-preview"), {"maintenance_message": "Typed but unsaved"})
    assert r.status_code == 200 and b"Typed but unsaved" in r.content and b"Preview:" in r.content
    assert SiteSettings.load().maintenance_message != "Typed but unsaved"


def test_new_pages_are_admin_only(client, student):
    client.force_login(student)
    for name, args in (("backup-settings", []), ("maintenance-save", []), ("maintenance-preview", []), ("backup-restore", ["lumen-backup-20260101-000000.zip"])):
        assert client.post(reverse(f"administration:{name}", args=args)).status_code == 403


# ---------- restore ----------

@pytest.mark.django_db(transaction=True)
def test_restore_round_trip(client, admin_user, student, settings):
    (settings.MEDIA_ROOT / "resources").mkdir(parents=True)
    (settings.MEDIA_ROOT / "resources" / "old.txt").write_text("from the backup")
    SiteSettings.objects.filter(pk=1).update(site_name="Before") if SiteSettings.objects.exists() else SiteSettings.load()
    SiteSettings.objects.filter(pk=1).update(site_name="Before")
    name = backups.create_backup()
    # change things after the backup
    SiteSettings.objects.filter(pk=1).update(site_name="After")
    student.delete()
    (settings.MEDIA_ROOT / "resources" / "old.txt").unlink()
    (settings.MEDIA_ROOT / "new.txt").write_text("made later")
    client.force_login(admin_user)
    r = client.post(reverse("administration:backup-restore", args=[name]), {"confirm": "RESTORE"})
    assert r.status_code == 302 and r["Location"].endswith(reverse("accounts:login") + "?restored=1")
    assert SiteSettings.load().site_name == "Before"
    assert type(student).objects.filter(username=student.username).exists()
    assert (settings.MEDIA_ROOT / "resources" / "old.txt").read_text() == "from the backup" and not (settings.MEDIA_ROOT / "new.txt").exists()
    assert len(backups.list_backups()) == 2  # the original and the safety copy of the state just before
    safety = [b for b in backups.list_backups() if b["name"] != name][0]["name"]
    with zipfile.ZipFile(backups.path_for(safety)) as z:
        assert json.loads(z.read("manifest.json"))["format"] == 1 and "media/new.txt" in z.namelist()
    assert AuditLog.objects.filter(action="backup_restored", target=name).exists()
    client.logout()
    assert not client.get(reverse("accounts:student-dashboard")).status_code == 200  # signed out everywhere


def test_restore_needs_the_typed_word(admin_client, student):
    name = backups.create_backup()
    student.delete()
    for confirm in ("", "restore", "yes"):
        r = admin_client.post(reverse("administration:backup-restore", args=[name]), {"confirm": confirm})
        assert r.status_code == 302 and r["Location"] == reverse("administration:backups")
    assert not type(student).objects.filter(username=student.username).exists()  # nothing was restored


@pytest.mark.parametrize("make", ["not-a-zip", "no-manifest", "bad-format", "bad-json", "evil-path"])
def test_unusable_backups_are_refused_before_anything_changes(admin_client, student, make):
    name = "lumen-backup-20260101-000000.zip"
    path = backups.backup_dir() / name
    if make == "not-a-zip":
        path.write_bytes(b"garbage")
    else:
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("data.json", "{not json" if make == "bad-json" else "[]")
            if make != "no-manifest":
                z.writestr("manifest.json", json.dumps({"format": 99 if make == "bad-format" else 1}))
            if make == "evil-path":
                z.writestr("media/../../escaped.txt", "x")
    before = SiteSettings.load().site_name
    r = admin_client.post(reverse("administration:backup-restore", args=[name]), {"confirm": "RESTORE"})
    assert r.status_code == 302 and r["Location"] == reverse("administration:backups")
    assert SiteSettings.load().site_name == before and type(student).objects.filter(pk=student.pk).exists()
    assert not (backups.backup_dir().parent / "escaped.txt").exists()
    assert len(backups.list_backups()) == 1  # no safety backup either: it failed at the checking stage


def test_restore_unknown_or_bad_name(admin_client):
    assert admin_client.post(reverse("administration:backup-restore", args=["lumen-backup-20260101-000000.zip"]), {"confirm": "RESTORE"}).status_code == 302
    assert admin_client.post("/admin-panel/backups/..%2Fx/restore/", {"confirm": "RESTORE"}).status_code in (302, 404)


def test_restore_command(db, student):
    from django.core.management import CommandError, call_command

    name = backups.create_backup()
    student.delete()
    call_command("restore_backup", name, yes=True)
    assert type(student).objects.filter(username=student.username).exists()
    with pytest.raises(CommandError):
        call_command("restore_backup", "lumen-backup-20200101-000000.zip", yes=True)


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(db):
    names = {backups.create_backup() for _ in range(3)}
    assert len(names) == 3 and len(backups.list_backups()) == 3
