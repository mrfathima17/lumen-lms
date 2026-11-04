import json
import re
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse

from apps.administration import email_templates
from apps.administration.forms import contrast
from apps.administration.models import EmailTemplate
from apps.core.models import AllowedNetwork, AuditLog, SiteSettings
from apps.grading import services as grading
from apps.grading.models import GradeBand


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


# ---------- IP rules ----------

def test_add_toggle_delete_rule(admin_client):
    r = admin_client.post(reverse("administration:access"), {"name": "Quiz lab", "cidr": "10.20.0.0/16", "scope": "quiz"})
    rule = AllowedNetwork.objects.get()
    assert r.status_code == 302 and rule.is_active and rule.scope == "quiz"
    admin_client.post(reverse("administration:rule-toggle", args=[rule.pk]))
    rule.refresh_from_db()
    assert not rule.is_active
    admin_client.post(reverse("administration:rule-delete", args=[rule.pk]))
    assert not AllowedNetwork.objects.exists()
    assert set(AuditLog.objects.values_list("action", flat=True)) >= {"ip_rule_added", "ip_rule_disabled", "ip_rule_deleted"}


@pytest.mark.parametrize("cidr", ["not-an-ip", "300.1.1.1/24", "0.0.0.0/0", "10.0.0.0/99", ""])
def test_bad_networks_rejected(admin_client, cidr):
    r = admin_client.post(reverse("administration:access"), {"name": "x", "cidr": cidr, "scope": "quiz"})
    assert r.status_code == 200 and not AllowedNetwork.objects.exists()


def test_rule_that_would_lock_the_admin_out_is_refused(admin_client):
    r = admin_client.post(reverse("administration:access"), {"name": "Other site", "cidr": "203.0.113.0/24", "scope": "admin"}, REMOTE_ADDR="198.51.100.9", follow=True)
    assert b"locked out" in r.content or b"lock" in r.content
    assert not AllowedNetwork.objects.exists()  # rolled back
    r = admin_client.post(reverse("administration:access"), {"name": "Whole site elsewhere", "cidr": "203.0.113.0/24", "scope": "all"}, REMOTE_ADDR="198.51.100.9")
    assert not AllowedNetwork.objects.exists()


def test_rule_that_includes_the_admin_is_accepted(admin_client):
    admin_client.post(reverse("administration:access"), {"name": "Me", "cidr": "198.51.100.0/24", "scope": "admin"}, REMOTE_ADDR="198.51.100.9")
    assert AllowedNetwork.objects.count() == 1
    assert admin_client.get(reverse("administration:users"), REMOTE_ADDR="198.51.100.9").status_code == 200
    assert admin_client.get(reverse("administration:users"), REMOTE_ADDR="192.0.2.1").status_code == 403


def test_removing_the_only_allowing_rule_cannot_lock_out(admin_client):
    mine = AllowedNetwork.objects.create(name="Me", cidr="198.51.100.0/24", scope="admin")
    AllowedNetwork.objects.create(name="Elsewhere", cidr="203.0.113.0/24", scope="admin")
    # turning off the rule that lets me in would leave only "Elsewhere" active -> refused
    admin_client.post(reverse("administration:rule-toggle", args=[mine.pk]), REMOTE_ADDR="198.51.100.9")
    mine.refresh_from_db()
    assert mine.is_active
    admin_client.post(reverse("administration:rule-delete", args=[mine.pk]), REMOTE_ADDR="198.51.100.9")
    assert AllowedNetwork.objects.filter(pk=mine.pk).exists()


def test_quiz_rule_applies_to_students_but_not_lecturer_editor(client, course, enrolled, student, lecturer, admin_client):
    admin_client.post(reverse("administration:access"), {"name": "Lab", "cidr": "10.0.0.0/8", "scope": "quiz"}, REMOTE_ADDR="203.0.113.5")
    assert AllowedNetwork.objects.get().scope == "quiz"
    client.force_login(student)
    assert client.get("/quizzes/", REMOTE_ADDR="203.0.113.5").status_code == 403
    assert client.get("/quizzes/", REMOTE_ADDR="10.1.1.1").status_code == 200


# ---------- system settings ----------

def test_settings_saved_and_used_elsewhere(admin_client):
    data = {"site_name": "Campus Learn", "late_penalty_percent_per_day": 5, "quiz_review_policy": "immediate", "attendance_warning_percent": 75,
            "private_files_quota_mb": 100, "audit_log_retention_months": 6, "two_factor_policy": "off", "maintenance_message": "Back soon"}
    assert admin_client.post(reverse("administration:settings"), data).status_code == 302
    s = SiteSettings.load()
    assert (s.site_name, s.late_penalty_percent_per_day, s.attendance_warning_percent, s.private_files_quota_mb) == ("Campus Learn", 5, 75, 100)
    assert b"Campus Learn" in admin_client.get(reverse("administration:users")).content
    assert "late_penalty_percent_per_day" in AuditLog.objects.get(action="settings_changed").detail


@pytest.mark.parametrize("field,value", [("late_penalty_percent_per_day", 101), ("attendance_warning_percent", 101), ("private_files_quota_mb", 0),
                                         ("audit_log_retention_months", 0), ("audit_log_retention_months", 121), ("site_name", "   ")])
def test_settings_validation(admin_client, field, value):
    data = {"site_name": "Lumen", "late_penalty_percent_per_day": 10, "quiz_review_policy": "after_close", "attendance_warning_percent": 80,
            "private_files_quota_mb": 500, "audit_log_retention_months": 12, "two_factor_policy": "off", "maintenance_message": "x", field: value}
    r = admin_client.post(reverse("administration:settings"), data)
    assert r.status_code == 200 and SiteSettings.load().site_name == "Lumen"


def test_maintenance_mode_from_the_screen(client, admin_client, student):
    base = {"site_name": "Lumen", "late_penalty_percent_per_day": 10, "quiz_review_policy": "after_close", "attendance_warning_percent": 80,
            "private_files_quota_mb": 500, "audit_log_retention_months": 12, "two_factor_policy": "off", "maintenance_message": "Upgrading the database tonight"}
    admin_client.post(reverse("administration:settings"), {**base, "maintenance_mode": "on"})
    assert b"Maintenance mode is on" in admin_client.get(reverse("administration:users")).content  # banner for admins
    sc = type(client)()  # a separate browser for the student
    sc.force_login(student)
    r = sc.get(reverse("accounts:student-dashboard"))
    assert r.status_code == 503 and b"Upgrading the database tonight" in r.content
    admin_client.post(reverse("administration:settings"), base)
    assert sc.get(reverse("accounts:student-dashboard")).status_code == 200


# ---------- grade scale ----------

def formset_data(rows, deleted=()):
    data = {"form-TOTAL_FORMS": len(rows), "form-INITIAL_FORMS": sum(1 for r in rows if r.get("id")), "form-MIN_NUM_FORMS": 0, "form-MAX_NUM_FORMS": 1000}
    for i, r in enumerate(rows):
        for k, v in r.items():
            data[f"form-{i}-{k}"] = v
        if i in deleted:
            data[f"form-{i}-DELETE"] = "on"
    return data


def test_grade_scale_page_lists_default_bands(admin_client):
    body = admin_client.get(reverse("administration:grade-scale")).content.decode()
    assert body.count('name="form-') > 12 * 3 and "A+" in body


def test_grade_scale_edit_changes_gpa_lookup(admin_client):
    rows = [{"min_percent": "50", "letter": "P", "points": "2.00"}, {"min_percent": "0", "letter": "F", "points": "0.00"}]
    GradeBand.objects.all().delete()
    r = admin_client.post(reverse("administration:grade-scale"), formset_data(rows))
    assert r.status_code == 302 and GradeBand.objects.count() == 2
    assert grading.band_for(Decimal("62")).letter == "P" and grading.band_for(Decimal("12")).letter == "F"


@pytest.mark.parametrize("rows,msg", [
    ([{"min_percent": "50", "letter": "P", "points": "2"}], "start at 0"),
    ([{"min_percent": "0", "letter": "F", "points": "0"}, {"min_percent": "0", "letter": "Z", "points": "1"}], "duplicate"),
    ([{"min_percent": "0", "letter": "", "points": "0"}], "Required"),
    ([{"min_percent": "101", "letter": "A", "points": "4"}, {"min_percent": "0", "letter": "F", "points": "0"}], "0 to 100"),
    ([{"min_percent": "0", "letter": "F", "points": "-1"}], "0 to 9.99"),
])
def test_grade_scale_validation(admin_client, rows, msg):
    GradeBand.objects.all().delete()
    r = admin_client.post(reverse("administration:grade-scale"), formset_data(rows))
    assert r.status_code == 200 and msg.lower() in r.content.decode().lower()
    assert GradeBand.objects.count() == 0


def test_grade_scale_cannot_be_emptied(admin_client):
    ids = list(GradeBand.objects.values_list("pk", flat=True))
    rows = [{"id": pk, "min_percent": "0", "letter": "x", "points": "0"} for pk in ids]
    r = admin_client.post(reverse("administration:grade-scale"), formset_data(rows, deleted=range(len(rows))))
    assert r.status_code == 200 and GradeBand.objects.count() == 12


# ---------- theme ----------

def theme_post(**over):
    """A complete, valid Theme & branding form; tests override single fields."""
    data = {"site_name": "Lumen", "brand_color": "#4f46e5", "brand_color2": "#7c3aed", "sidebar_color": "#171a2e", "font": "system", "radius": "12",
            "login_bg": "", "default_mode": "light", "allow_dark_mode": "on"}
    data.update(over)
    return data


def test_contrast_helper():
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#ffffff", "#ffffff") == pytest.approx(1)


def test_theme_saved_reaches_every_page_and_dark_mode_rules(client, admin_client, student):
    r = admin_client.post(reverse("administration:theme"), theme_post(brand_color="#0f766e", sidebar_color="#0b1f1d", default_mode="dark", allow_dark_mode=""))
    assert r.status_code == 302
    s = SiteSettings.load()
    assert (s.brand_color, s.sidebar_color, s.default_mode, s.allow_dark_mode) == ("#0f766e", "#0b1f1d", "dark", False)
    client.force_login(student)
    page = client.get(reverse("accounts:student-dashboard")).content.decode()
    data = json.loads(re.search(r'<script id="lumen-theme-data" type="application/json">(.*?)</script>', page).group(1))
    assert data == {"brand": "#0f766e", "brand2": "#7c3aed", "sidebar": "#0b1f1d", "font": "system", "radius": 12, "loginBg": "", "defaultMode": "dark", "allowDark": False}


@pytest.mark.parametrize("brand,sidebar,field", [("#ffff00", "#171a2e", "brand_color"), ("#4f46e5", "#ffffff", "sidebar_color"), ("red", "#171a2e", "brand_color"), ("#12345", "#171a2e", "brand_color")])
def test_unreadable_or_invalid_colours_refused(admin_client, brand, sidebar, field):
    r = admin_client.post(reverse("administration:theme"), theme_post(brand_color=brand, sidebar_color=sidebar))
    assert r.status_code == 200 and SiteSettings.load().brand_color == "#4f46e5"


def test_theme_reset(admin_client):
    s = SiteSettings.load(); s.brand_color = "#0f766e"; s.save()
    admin_client.post(reverse("administration:theme"), {"reset": "1"})
    assert SiteSettings.load().brand_color == "#4f46e5"


def test_theme_data_cannot_break_out_of_the_page(client, student):
    s = SiteSettings.load(); s.brand_color = '</script><script>alert(1)</script>'[:7]; s.save()
    client.force_login(student)
    assert b"<script>alert" not in client.get(reverse("accounts:student-dashboard")).content


# ---------- email templates ----------

def test_default_template_used_until_customised(admin_client, student):
    admin_client.post(reverse("administration:user-new"), {"username": "newbie", "first_name": "Nila", "last_name": "S", "email": "n@example.com", "role": "student"})
    assert mail.outbox[0].subject == "Your Lumen account" and "Sample password:" in mail.outbox[0].body


def test_customised_welcome_email_is_used(admin_client):
    body = "Hi {name}! Your login is {username} / {password} at {login_url} ({site})."
    r = admin_client.post(reverse("administration:email-template", args=["welcome"]), {"subject": "Welcome to {site}", "body": body})
    assert r.status_code == 302 and EmailTemplate.objects.get().key == "welcome"
    admin_client.post(reverse("administration:user-new"), {"username": "newbie", "first_name": "Nila", "last_name": "S", "email": "n@example.com", "role": "student"})
    m = mail.outbox[-1]
    assert m.subject == "Welcome to Lumen" and m.body.startswith("Hi Nila S! Your login is newbie / ") and "/sign-in/" in m.body


def test_password_reset_uses_its_own_template(admin_client, student):
    student.email = "s@example.com"; student.save()
    admin_client.post(reverse("administration:user-reset", args=[student.pk]))
    assert "reset" in mail.outbox[-1].subject.lower()


def test_template_validation(admin_client):
    url = reverse("administration:email-template", args=["welcome"])
    r = admin_client.post(url, {"subject": "Hi {site} {secret}", "body": "Use {password}"})
    assert r.status_code == 200 and b"Unknown placeholder" in r.content
    r = admin_client.post(url, {"subject": "Hi", "body": "No way to log in"})
    assert r.status_code == 200 and b"must include" in r.content
    assert not EmailTemplate.objects.exists()
    assert admin_client.get(reverse("administration:email-template", args=["nonsense"])).status_code == 403


def test_template_cannot_read_other_data():
    assert email_templates.fill("{password} {user.password} {__class__}", {"password": "x"}) == "x {user.password} {__class__}"
    assert email_templates.unknown_placeholders("{name} {nope} {password}") == ["nope"]


def test_template_reset_and_test_send(admin_client, admin_user):
    url = reverse("administration:email-template", args=["welcome"])
    admin_client.post(url, {"subject": "Custom {site}", "body": "pw {password}"})
    admin_user.email = "admin@example.com"; admin_user.save()
    admin_client.post(url, {"subject": "Custom {site}", "body": "pw {password}", "send_test": "1"})
    assert mail.outbox[-1].to == ["admin@example.com"] and mail.outbox[-1].subject.startswith("[Test]")
    assert mail.outbox[-1].body == "pw Sample-Pass-123"
    admin_client.post(url, {"reset": "1"})
    assert not EmailTemplate.objects.exists()


# ---------- permissions ----------

def test_only_admins_reach_part_two_pages(client, student, lecturer):
    names = [("access", []), ("settings", []), ("grade-scale", []), ("theme", []), ("email-templates", []), ("email-template", ["welcome"])]
    for u in (student, lecturer):
        client.force_login(u)
        for n, a in names:
            assert client.get(reverse(f"administration:{n}", args=a)).status_code == 403
        assert client.post(reverse("administration:settings"), {"site_name": "Hacked"}).status_code == 403
        assert client.post(reverse("administration:rule-delete", args=[1])).status_code == 403
    assert SiteSettings.load().site_name == "Lumen"
    anon = type(client)()
    assert all(anon.get(reverse(f"administration:{n}", args=a)).status_code == 302 for n, a in names)


def test_nav_links(admin_client):
    page = admin_client.get(reverse("accounts:admin-overview")).content
    for n in ("access", "settings", "theme", "email-templates"):
        assert reverse(f"administration:{n}").encode() in page
