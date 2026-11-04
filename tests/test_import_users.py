import csv
import io

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import User
from apps.administration import services
from apps.core.models import AuditLog
from apps.courses.models import Enrolment

IMPORT, CONFIRM, ERRORS = "administration:import", "administration:import-confirm", "administration:import-errors"


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def upload(text, **opts):
    return {"file": SimpleUploadedFile("users.csv", text.encode(), content_type="text/csv"), "opts": "1", "default_role": "student",
            "send_email": "on", "force_change": "on", "skip_existing": "on", **opts}


def posted(text, **opts):
    """What the page's own buttons post: the CSV in the hidden field plus the options (an unchecked switch is simply absent)."""
    return {"text": text, "opts": "1", "default_role": "student", "send_email": "on", "force_change": "on", "skip_existing": "on", **opts}


def drop(data, *names):
    for n in names:
        data.pop(n, None)
    return data


# ---------- the page ----------

def test_empty_page_has_the_three_cards(admin_client):
    html = admin_client.get(reverse(IMPORT)).content.decode()
    for text in ("1 · Upload", "Drop users.csv here", "2 · Options", "Default role", "Default sample password", "Send welcome email to each user",
                 "Force password change at first login", "Skip rows that already exist", "3 · Preview", "No file yet"):
        assert text in html, text
    assert "Import " not in html.replace("Bulk user import", "")


def test_preview_summary_rows_and_buttons(admin_client, student):
    text = f"username,first_name,last_name\nnew1,Kasun,Perera\n{student.username},Ravindu,Jay\nbad name,No,Good\n"
    html = admin_client.post(reverse(IMPORT), upload(text)).content.decode()
    assert "3 rows read · 1 valid · 2 with errors" in html
    assert 'pill ok" title' not in html and ">OK<" in html and ">Duplicate<" in html and ">Bad username<" in html
    assert "Import 1 user" in html and "Download error report" in html and "users.csv" in html
    assert not User.objects.filter(username="new1").exists()  # previewing creates nothing


def test_no_buttons_for_a_clean_or_hopeless_file(admin_client):
    html = admin_client.post(reverse(IMPORT), upload("username\nfine1\nfine2\n")).content.decode()
    assert "Import 2 users" in html and "Download error report" not in html
    html = admin_client.post(reverse(IMPORT), upload("username\nbad name\n")).content.decode()
    assert "Import " not in html.replace("Bulk user import", "") and "No row can be imported" in html


def test_changing_an_option_rechecks_the_same_file_without_uploading_again(admin_client):
    text = "username,role\nx1,\nx2,lecturer\n"
    html = admin_client.post(reverse(IMPORT), posted(text, default_role="lecturer", filename="users.csv")).content.decode()
    assert "2 rows read · 2 valid" in html and "users.csv" in html
    assert 'value="lecturer" selected' in html


def test_post_without_a_file_asks_for_one(admin_client):
    assert b"Choose a CSV file first" in admin_client.post(reverse(IMPORT), {"opts": "1"}).content


def test_preview_lists_at_most_200_rows_but_counts_all(admin_client):
    text = "username\n" + "\n".join(f"u{i}" for i in range(300))
    html = admin_client.post(reverse(IMPORT), upload(text)).content.decode()
    assert "300 rows read · 300 valid" in html and "Showing the first 200 of 300" in html and html.count("<td>u") == 200


# ---------- options ----------

def test_default_role_fills_blank_role_cells_only(admin_client):
    admin_client.post(reverse(CONFIRM), posted("username,role\na1,\na2,student\na3,Administrator\n", default_role="lecturer"))
    assert [User.objects.get(username=u).role for u in ("a1", "a2", "a3")] == ["lecturer", "student", "admin"]


def test_shared_sample_password(admin_client):
    r = admin_client.post(reverse(CONFIRM), posted("username\np1\np2\n", sample_password="Lumen@2026!"))
    assert r.status_code == 302
    for name in ("p1", "p2"):
        assert User.objects.get(username=name).check_password("Lumen@2026!")
    page = admin_client.get(r["Location"]).content.decode()
    assert page.count("<code>Lumen@2026!</code>") == 2


def test_random_passwords_differ_when_left_empty(admin_client):
    r = admin_client.post(reverse(CONFIRM), posted("username\nr1\nr2\n"))
    page = admin_client.get(r["Location"]).content.decode()
    codes = {c for c in __import__("re").findall(r"<code>([^<]+)</code>", page)}
    assert len(codes) == 2 and all(len(c) == 14 for c in codes)


@pytest.mark.parametrize("pw", ["short", "1234567890", "password123"])
def test_weak_sample_password_refused_and_nothing_created(admin_client, settings, pw):
    settings.AUTH_PASSWORD_VALIDATORS = [
        {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
        {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
        {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    ]
    r = admin_client.post(reverse(CONFIRM), posted("username\nw1\n", sample_password=pw))
    assert r.status_code == 200 and not User.objects.filter(username="w1").exists()


def test_welcome_email_switch(admin_client):
    admin_client.post(reverse(CONFIRM), posted("username,email\ne1,e1@example.com\n"))
    assert len(mail.outbox) == 1
    mail.outbox.clear()
    data = drop(posted("username,email\ne2,e2@example.com\n"), "send_email")
    r = admin_client.post(reverse(CONFIRM), data)
    assert len(mail.outbox) == 0
    assert "Not sent (switched off)" in admin_client.get(r["Location"]).content.decode()


def test_force_password_change_switch(admin_client):
    admin_client.post(reverse(CONFIRM), posted("username\nf1\n"))
    admin_client.post(reverse(CONFIRM), drop(posted("username\nf2\n"), "force_change"))
    assert User.objects.get(username="f1").must_change_password and not User.objects.get(username="f2").must_change_password


def test_skip_existing_on_skips_duplicates_and_off_refuses_the_import(admin_client, student):
    text = f"username\n{student.username}\nfresh1\n"
    admin_client.post(reverse(CONFIRM), posted(text))
    assert User.objects.filter(username="fresh1").exists()
    User.objects.filter(username="fresh1").delete()
    r = admin_client.post(reverse(CONFIRM), drop(posted(text), "skip_existing"))
    assert r.status_code == 200 and b"Nothing was imported: 1 row already exist" in r.content or b"Nothing was imported: 1 row" in r.content
    assert not User.objects.filter(username="fresh1").exists()


def test_direct_post_without_the_marker_keeps_the_old_defaults(admin_client):
    admin_client.post(reverse(CONFIRM), {"text": "username,email\nlegacy,l@example.com\n"})
    assert User.objects.get(username="legacy").must_change_password and len(mail.outbox) == 1


# ---------- columns and error report ----------

def test_course_codes_header_is_accepted(admin_client, course):
    admin_client.post(reverse(CONFIRM), posted("username,course_codes\ncc1,CS201\n"))
    assert Enrolment.objects.filter(course=course, user__username="cc1").exists()
    assert services.parse_csv("username,Course_Codes\nx,CS201\n")[0][0]["courses"] == "CS201"


def test_error_report_lists_only_problem_rows_with_the_reason(admin_client, student):
    text = f"username,first_name,email\nok1,A,\n{student.username},B,\nbad name,C,\nbademail,D,nope\n=cmd,E,\n"
    r = admin_client.post(reverse(ERRORS), posted(text))
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv") and "attachment" in r["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][0] == "line" and rows[0][-1] == "problem"
    names = [row[1] for row in rows[1:]]
    assert "ok1" not in names and student.username in names and "bad name" in names and "bademail" in names
    assert any("already exists" in row[-1] for row in rows[1:]) and any("email is not valid" in row[-1] for row in rows[1:])
    assert "'=cmd" in r.content.decode()  # formulas are neutralised


def test_error_report_for_a_broken_file_goes_back(admin_client):
    assert admin_client.post(reverse(ERRORS), {"text": ""}).status_code == 302


def test_new_urls_are_admin_only_and_post_only(client, student, admin_client):
    client.force_login(student)
    assert client.post(reverse(ERRORS), {"text": "username\na\n"}).status_code == 403
    assert admin_client.get(reverse(ERRORS)).status_code == 405


def test_labels_are_short_and_specific(db):
    rows = services.validate_rows(services.parse_csv("username,email,role\nbad name,,\nok,x,\nr,,wizard\n")[0])
    assert [r["label"] for r in rows] == ["Bad username", "Bad email", "Bad role"] and all(r["status"] == "error" for r in rows)
