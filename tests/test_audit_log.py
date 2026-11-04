from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.audit_text import CATEGORIES, describe, when
from apps.core.models import AllowedNetwork, AuditLog


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def row(action, target="", detail="", **kw):
    return AuditLog(action=action, target=target, detail=detail, **kw)


@pytest.mark.parametrize("action,target,detail,text", [
    ("user_created", "s2026-0377", "role student", "Created user s2026-0377 (Student)"),
    ("user_updated", "kasun", "role student → lecturer", "Changed role: kasun → Lecturer"),
    ("user_updated", "kasun", "", "Edited user kasun"),
    ("sign_in", "admin", "", "Signed in"),
    ("sign_in", "admin", "two-factor", "Signed in (two-factor)"),
    ("login_failed", "kasun", "wrong password", "Failed login (wrong password)"),
    ("ip_blocked", "/quizzes/3/", "", "Tried to open /quizzes/3/"),
    ("quiz_saved", "CS201", "Quiz 3", "Saved quiz Quiz 3 (CS201)"),
    ("settings_changed", "", "late_penalty_percent_per_day, site_name", "Changed settings: late penalty, site name"),
    ("theme_changed", "", "brand_color, brand_color2, login_bg, remove_login_image", "Changed theme: primary colour, secondary colour, login background, login image removed"),
    ("users_imported", "", "2 created, 1 skipped", "Imported users: 2 created, 1 skipped"),
    ("some_future_action", "x", "y", "Some future action x (y)"),
])
def test_event_sentences(action, target, detail, text):
    assert describe(row(action, target, detail)) == text


def test_every_recorded_action_has_a_sentence():
    """Every audit.record() call in the code must be known to the display layer (no raw names on screen)."""
    import pathlib
    import re

    from apps.core.audit_text import EVENTS

    names = set()
    for p in pathlib.Path("apps").rglob("*.py"):
        names |= set(re.findall(r'audit\.record\([^,)]+,\s*"([a-z_0-9]+)"', p.read_text(encoding="utf-8")))
        names |= set(re.findall(r'audit\.record\([^,)]+,\s*"([a-z_0-9]+)"\s+if\s+[^"]+else\s+"([a-z_0-9]+)"', p.read_text(encoding="utf-8")))
    flat = {n for item in names for n in ((item,) if isinstance(item, str) else item)}
    assert flat - set(EVENTS) == set(), flat - set(EVENTS)


def test_time_hides_the_year_only_for_this_year():
    now = timezone.now()
    assert str(timezone.localtime(now).year) not in when(now)
    assert "2020" in when(now.replace(year=2020))


def test_table_columns_and_pills(admin_client, admin_user):
    AuditLog.objects.create(user=admin_user, action="user_created", target="newbie", detail="role student", ip_address="10.0.0.1")
    AuditLog.objects.create(action="login_failed", target="kasun", detail="wrong password", result="failed", ip_address="10.0.0.2")
    AuditLog.objects.create(action="ip_blocked", target="/quizzes/3/", result="blocked", ip_address="112.134.20.8")
    html = admin_client.get(reverse("administration:audit")).content.decode()
    for head in ("<th>Time</th>", "<th>User</th>", "<th>Event</th>", "<th>IP address</th>", "<th>Result</th>"):
        assert head in html
    for gone in ("<th>When</th>", "<th>Who</th>", "<th>Target</th>", "<th>Detail</th>", "<th>Action</th>"):
        assert gone not in html
    assert "Created user newbie (Student)" in html and "Failed login (wrong password)" in html and "Tried to open /quizzes/3/" in html
    assert 'pill ok">Success' in html and 'pill warn">Failed' in html and 'pill bad">Blocked by IP rule' in html
    assert ">sign_in<" not in html and ">user_created<" not in html  # no raw action names on screen


def test_failed_login_user_column_shows_the_account_tried(admin_client):
    AuditLog.objects.create(action="login_failed", target="kasun", result="failed")
    html = admin_client.get(reverse("administration:audit") + "?user=kasun").content.decode()
    assert "Failed login" in html


@pytest.mark.parametrize("key", [k for k, _, _ in CATEGORIES])
def test_every_category_filter_works(admin_client, key):
    assert admin_client.get(reverse("administration:audit") + f"?category={key}").status_code == 200


def test_category_filters_pick_the_right_rows(admin_client, admin_user):
    AuditLog.objects.create(user=admin_user, action="user_updated", target="kasun", detail="role student → lecturer")
    AuditLog.objects.create(user=admin_user, action="user_updated", target="nimal", detail="")
    AuditLog.objects.create(user=admin_user, action="settings_changed", detail="site_name")
    url = reverse("administration:audit")
    roles = admin_client.get(url + "?category=roles").content.decode()
    assert "Changed role: kasun" in roles and "Edited user nimal" not in roles and "Changed settings" not in roles
    assert "Changed settings" in admin_client.get(url + "?category=settings").content.decode()
    assert admin_client.get(url + "?category=nonsense").status_code == 200


def test_wrong_password_is_audited_without_the_password(client, student):
    client.post(reverse("accounts:login"), {"username": student.username, "password": "totally-wrong-pw"})
    e = AuditLog.objects.get(action="login_failed")
    assert (e.target, e.detail, e.result) == (student.username, "wrong password", "failed")
    assert "totally-wrong-pw" not in f"{e.target}{e.detail}"


def test_unknown_username_is_not_stored(client, db):
    client.post(reverse("accounts:login"), {"username": "hunter2-typed-in-wrong-box", "password": "x"})
    e = AuditLog.objects.get(action="login_failed")
    assert e.target == "" and e.detail == "unknown user"


def test_sign_out_is_no_longer_recorded(client, student):
    client.force_login(student)
    client.post(reverse("accounts:logout"))
    assert not AuditLog.objects.filter(action="sign_out").exists()


def test_blocked_request_is_audited_once_a_minute(client, student, db):
    AllowedNetwork.objects.create(name="campus only", cidr="10.99.0.0/16", scope="all", is_active=True)
    client.force_login(student)
    for _ in range(3):
        assert client.get(reverse("accounts:student-dashboard")).status_code == 403
    blocked = AuditLog.objects.filter(action="ip_blocked")
    assert blocked.count() == 1 and blocked.get().result == "blocked" and blocked.get().user == student
    AuditLog.objects.filter(pk=blocked.get().pk).update(created_at=timezone.now() - timedelta(minutes=2))
    client.get(reverse("accounts:student-dashboard"))
    assert AuditLog.objects.filter(action="ip_blocked").count() == 2
