from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.administration import services
from apps.core.models import AuditLog, SiteSettings
from apps.courses.models import Enrolment

User = get_user_model()
GOOD = {"username": "newbie", "first_name": "Nila", "last_name": "Silva", "email": "nila@example.com", "role": "student", "index_number": "2026-0999", "faculty": "Computing"}


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


# ---------- creating users ----------

def test_create_user_generates_password_emails_it_and_forces_change(admin_client):
    r = admin_client.post(reverse("administration:user-new"), GOOD)
    u = User.objects.get(username="newbie")
    assert r.status_code == 302 and u.must_change_password and u.role == "student" and not u.has_usable_password() is False
    assert len(mail.outbox) == 1 and u.username in mail.outbox[0].body and "Sample password:" in mail.outbox[0].body
    page = admin_client.get(r["Location"]).content.decode()
    assert "shown once" in page
    password = mail.outbox[0].body.split("Sample password: ")[1].split("\n")[0]
    assert u.check_password(password) and f"<code>{password}</code>" in page
    assert "shown once" not in admin_client.get(r["Location"]).content.decode()  # gone on the next view
    assert AuditLog.objects.filter(action="user_created", target="newbie").exists()
    assert password not in "".join(AuditLog.objects.values_list("detail", flat=True))  # never written to the log


def test_new_user_must_change_password_at_first_sign_in(client, admin_client):
    admin_client.post(reverse("administration:user-new"), GOOD)
    password = mail.outbox[0].body.split("Sample password: ")[1].split("\n")[0]
    c = type(client)()
    assert c.post(reverse("accounts:login"), {"username": "newbie", "password": password}).status_code == 302
    r = c.get(reverse("accounts:student-dashboard"))
    assert r.status_code == 302 and reverse("accounts:password-change") in r["Location"]


def test_no_email_means_no_mail_but_password_still_shown(admin_client):
    admin_client.post(reverse("administration:user-new"), {**GOOD, "email": ""})
    assert mail.outbox == []
    u = User.objects.get(username="newbie")
    assert b"No email address" in admin_client.get(reverse("administration:user-edit", args=[u.pk])).content


def test_duplicate_username_and_index_rejected(admin_client, student):
    student.index_number = "2026-0142"
    student.save()
    assert admin_client.post(reverse("administration:user-new"), {**GOOD, "username": "S2026-0142"}).status_code == 200
    assert admin_client.post(reverse("administration:user-new"), {**GOOD, "index_number": "2026-0142"}).status_code == 200
    assert not User.objects.filter(username="newbie").exists()


def test_generated_passwords_are_strong_and_different():
    pws = {services.generate_password() for _ in range(50)}
    assert len(pws) == 50
    assert all(len(p) == 14 and any(c.isdigit() for c in p) and any(c.isupper() for c in p) and any(c.islower() for c in p) for p in pws)


# ---------- editing, resetting, disabling ----------

def test_edit_user_and_audit_role_change(admin_client, student):
    r = admin_client.post(reverse("administration:user-edit", args=[student.pk]), {**GOOD, "username": student.username, "role": "lecturer", "index_number": ""})
    student.refresh_from_db()
    assert r.status_code == 302 and student.role == "lecturer" and student.index_number is None
    assert "student → lecturer" in AuditLog.objects.get(action="user_updated").detail


def test_reset_password(admin_client, student):
    student.must_change_password = False
    student.save()
    old = student.password
    admin_client.post(reverse("administration:user-reset", args=[student.pk]))
    student.refresh_from_db()
    assert student.password != old and student.must_change_password
    assert AuditLog.objects.filter(action="password_reset", target=student.username).exists()
    assert admin_client.get(reverse("administration:user-reset", args=[student.pk])).status_code == 405


def test_disable_blocks_sign_in_and_kills_existing_session(client, admin_client, student):
    student_client = type(client)()
    student_client.force_login(student)
    assert student_client.get(reverse("accounts:student-dashboard")).status_code == 200
    admin_client.post(reverse("administration:user-toggle", args=[student.pk]))
    student.refresh_from_db()
    assert not student.is_active
    assert student_client.get(reverse("accounts:student-dashboard")).status_code == 302  # session no longer valid
    assert type(client)().post(reverse("accounts:login"), {"username": student.username, "password": "Pass-12345-xyz"}).status_code == 200  # form re-shown, not signed in
    admin_client.post(reverse("administration:user-toggle", args=[student.pk]))
    student.refresh_from_db()
    assert student.is_active


def test_admin_cannot_lock_themselves_out(admin_client, admin_user):
    assert admin_client.post(reverse("administration:user-toggle", args=[admin_user.pk])).status_code == 403
    r = admin_client.post(reverse("administration:user-edit", args=[admin_user.pk]), {**GOOD, "username": admin_user.username, "role": "student", "index_number": ""})
    assert r.status_code == 403
    admin_user.refresh_from_db()
    assert admin_user.is_active and admin_user.role == "admin"


def test_last_active_admin_is_protected(admin_user, make_user):
    other = make_user("admin2", "admin")
    services.check_can_change(admin_user, other, new_active=False)  # fine: admin_user remains
    other.is_active = False
    other.save()
    third = make_user("admin3", "lecturer")
    with pytest.raises(PermissionDenied):
        services.check_can_change(third, admin_user, new_active=False)  # would leave no active admin
    with pytest.raises(PermissionDenied):
        services.check_can_change(third, admin_user, new_role="lecturer")


# ---------- listing and export ----------

def test_user_search_and_filters(admin_client, student, lecturer, admin_user):
    url = reverse("administration:users")
    body = admin_client.get(url + "?q=amal").content
    assert b"s2026-0142" in body and b"nperera" not in body
    assert b"nperera" in admin_client.get(url + "?role=lecturer").content and b"s2026-0142" not in admin_client.get(url + "?role=lecturer").content
    lecturer.is_active = False
    lecturer.save()
    assert b"nperera" in admin_client.get(url + "?status=disabled").content and b"s2026-0142" not in admin_client.get(url + "?status=disabled").content
    assert admin_client.get(url + "?page=999&role=bogus").status_code == 200


def test_users_csv_export_guards_formulas(admin_client, student):
    student.first_name = "=CMD()"
    student.save()
    r = admin_client.get(reverse("administration:users-export"))
    text = r.content.decode()
    assert r["Content-Type"].startswith("text/csv") and "'=CMD()" in text and ",=" not in text
    assert "password" not in text.lower().split("\n")[0]


# ---------- bulk import ----------

def csv_file(text):
    return SimpleUploadedFile("users.csv", text.encode(), content_type="text/csv")


def test_import_preview_flags_problems_and_creates_nothing(admin_client, student, course):
    text = ("username,first_name,last_name,email,role,index_number,courses\n"
            "ok1,Ann,Lee,ann@example.com,student,2026-1001,CS201\n"
            f"{student.username},Dup,User,,student,,\n"
            "bad name,Space,Name,,student,,\n"
            "ok1,Again,Twice,,student,,\n"
            "badmail,Bad,Mail,not-an-email,student,,\n"
            "badrole,Bad,Role,,wizard,,\n"
            "nocourse,No,Course,,student,,XX99\n"
            "lect1,Lee,Turer,,lecturer,,CS201\n")
    r = admin_client.post(reverse("administration:import"), {"file": csv_file(text)})
    body = r.content.decode()
    assert r.status_code == 200 and "8 rows read" in body and "1 valid" in body and "7 with errors" in body
    for problem in ("username already exists", "may only contain", "appears twice", "email is not valid", "role must be", "unknown course XX99", "only students can be enrolled"):
        assert problem in body
    assert not User.objects.filter(username="ok1").exists()


def test_import_confirm_creates_valid_rows_enrols_and_shows_passwords_once(admin_client, course):
    text = "username,first_name,last_name,email,role,courses\nann,Ann,Lee,ann@example.com,student,CS201\nbob,Bob,Ray,,Lecturer,\nbad user,x,y,,student,\n"
    r = admin_client.post(reverse("administration:import-confirm"), {"text": text})
    assert r.status_code == 302
    ann, bob = User.objects.get(username="ann"), User.objects.get(username="bob")
    assert ann.must_change_password and bob.role == "lecturer" and not User.objects.filter(username="bad user").exists()
    assert Enrolment.objects.filter(course=course, user=ann).exists()
    assert len(mail.outbox) == 1  # only Ann has an email
    page = admin_client.get(r["Location"]).content.decode()
    assert "<code>" in page and "ann" in page
    assert admin_client.get(r["Location"]).status_code == 302  # shown once
    assert AuditLog.objects.get(action="users_imported").detail == "2 created, 1 skipped"


def test_import_confirm_never_trusts_the_hidden_field(admin_client, student):
    text = f"username,role\n{student.username},administrator\nnewone,student\n"
    admin_client.post(reverse("administration:import-confirm"), {"text": text})
    student.refresh_from_db()
    assert student.role == "student" and User.objects.filter(username="newone").exists()
    assert User.objects.filter(role="admin").count() == 1  # only the existing admin


@pytest.mark.parametrize("content,msg", [("", "empty"), ("name,email\nx,y\n", "username"), ("username\n", "no users")])
def test_import_rejects_bad_files(admin_client, content, msg):
    r = admin_client.post(reverse("administration:import"), {"file": csv_file(content)})
    assert r.status_code == 200 and msg in r.content.decode().lower() and not User.objects.filter(username="x").exists()


def test_import_limits_and_type(admin_client):
    r = admin_client.post(reverse("administration:import"), {"file": SimpleUploadedFile("u.txt", b"username\na\n")})
    assert b"Upload a .csv file" in r.content
    big = "username\n" + "\n".join(f"u{i}" for i in range(1001))
    assert b"At most 1000" in admin_client.post(reverse("administration:import"), {"file": csv_file(big)}).content
    assert b"not UTF-8" in admin_client.post(reverse("administration:import"), {"file": SimpleUploadedFile("u.csv", b"username\n\xff\xfe\n")}).content
    assert b"larger than 1 MB" in admin_client.post(reverse("administration:import"), {"file": SimpleUploadedFile("u.csv", b"username\n" + b"a" * 1024 * 1024)}).content


def test_import_accepts_bom_and_case_insensitive_headers(admin_client):
    text = "﻿Username,Role\nbomuser,STUDENT\n"
    admin_client.post(reverse("administration:import-confirm"), {"text": text})
    assert User.objects.get(username="bomuser").role == "student"


# ---------- audit log ----------

def test_audit_log_filters_and_pagination(admin_client, admin_user, student):
    for i in range(60):
        AuditLog.objects.create(user=admin_user, action="user_created", target=f"user{i}")
    AuditLog.objects.create(user=student, action="grade_item_added", target="CS201", detail="Final exam")
    url = reverse("administration:audit")
    assert admin_client.get(url).context["page"].paginator.num_pages == 2
    assert b"Final exam" in admin_client.get(url + "?q=final").content and b"user5" not in admin_client.get(url + "?q=final").content
    assert b"Added grade item Final exam (CS201)" in admin_client.get(url + "?category=grades&user=S2026-0142").content
    assert admin_client.get(url + "?since=garbage").status_code == 200
    future = (timezone.localdate() + timedelta(days=2)).isoformat()
    assert b"No entries" in admin_client.get(url + f"?since={future}").content


def test_purge_command_respects_retention(db, admin_user):
    from django.core.management import call_command
    old = AuditLog.objects.create(user=admin_user, action="old")
    AuditLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
    recent = AuditLog.objects.create(user=admin_user, action="recent")
    call_command("purge_audit_log")
    assert list(AuditLog.objects.values_list("pk", flat=True)) == [recent.pk]
    s = SiteSettings.load(); s.audit_log_retention_months = 1; s.save()
    AuditLog.objects.filter(pk=recent.pk).update(created_at=timezone.now() - timedelta(days=45))
    call_command("purge_audit_log")
    assert not AuditLog.objects.exists()


# ---------- permissions ----------

def test_only_administrators_can_use_these_pages(client, student, lecturer, make_user):
    target = make_user("victim", "student")
    urls = [reverse("administration:users"), reverse("administration:users-export"), reverse("administration:user-new"), reverse("administration:user-edit", args=[target.pk]),
            reverse("administration:import"), reverse("administration:import-result"), reverse("administration:audit")]
    posts = [reverse("administration:user-reset", args=[target.pk]), reverse("administration:user-toggle", args=[target.pk]), reverse("administration:import-confirm")]
    for u in (student, lecturer):
        client.force_login(u)
        assert all(client.get(url).status_code == 403 for url in urls)
        assert all(client.post(url, {"text": "username\nhack\n"}).status_code == 403 for url in posts)
    target.refresh_from_db()
    assert target.is_active and not User.objects.filter(username="hack").exists()
    anon = type(client)()
    assert all(anon.get(url).status_code == 302 for url in urls)


def test_admin_pages_respect_the_admin_network_rule(admin_client):
    from apps.core.models import AllowedNetwork
    AllowedNetwork.objects.create(name="Campus", cidr="10.0.0.0/8", scope="admin", is_active=True)
    assert admin_client.get(reverse("administration:users"), REMOTE_ADDR="203.0.113.5").status_code == 403
    assert admin_client.get(reverse("administration:users"), REMOTE_ADDR="10.1.2.3").status_code == 200


def test_nav_links_for_admin(admin_client):
    page = admin_client.get(reverse("accounts:admin-overview")).content
    for n in ("users", "import", "audit"):
        assert reverse(f"administration:{n}").encode() in page
