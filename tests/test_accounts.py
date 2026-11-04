import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.core.models import AuditLog

PW = "Pass-12345-xyz"


def login(client, username, password=PW):
    return client.post(reverse("accounts:login"), {"username": username, "password": password})


def test_public_home_for_anonymous(client, db):
    r = client.get("/")
    assert r.status_code == 200 and b"Sign in" in r.content


@pytest.mark.parametrize("role,url", [("student", "/student/"), ("lecturer", "/lecturer/"), ("admin", "/admin-panel/")])
def test_sign_in_lands_on_role_dashboard(client, make_user, role, url):
    make_user("u1", role)
    r = login(client, "u1")
    assert r.status_code == 302 and r.url == reverse("accounts:home")
    r = client.get(reverse("accounts:home"))
    assert r.status_code == 302 and r.url == url
    assert client.get(url).status_code == 200


def test_wrong_password_shows_error(client, student):
    r = login(client, student.username, "nope")
    assert r.status_code == 200 and b"do not match" in r.content


def test_dashboards_are_role_protected(client, student, lecturer):
    client.force_login(student)
    assert client.get("/lecturer/").status_code == 403
    assert client.get("/admin-panel/").status_code == 403
    client.force_login(lecturer)
    assert client.get("/student/").status_code == 403


def test_anonymous_redirected_to_sign_in(client, db):
    r = client.get("/student/")
    assert r.status_code == 302 and r.url.startswith("/sign-in/")


def test_logout_requires_post_and_ends_session(client, student):
    client.force_login(student)
    assert client.get("/sign-out/").status_code == 405
    assert client.post("/sign-out/").status_code == 302
    assert client.get("/student/").status_code == 302


def test_forced_password_change(client, make_user):
    u = make_user("newbie", "student", must_change_password=True)
    login(client, "newbie")
    r = client.get("/student/")
    assert r.status_code == 302 and r.url == reverse("accounts:password-change")
    r = client.post(reverse("accounts:password-change"), {"old_password": PW, "new_password1": "Brand-new-pw-987", "new_password2": "Brand-new-pw-987"})
    assert r.status_code == 302
    u.refresh_from_db()
    assert not u.must_change_password and u.check_password("Brand-new-pw-987")
    assert client.get("/student/").status_code == 200


def test_lockout_after_five_failures(client, student):
    for _ in range(5):
        login(client, student.username, "bad")
    r = login(client, student.username)  # correct password, but locked
    assert r.status_code == 429
    assert b"Account locked" in r.content


def test_superuser_gets_admin_role(db):
    u = User.objects.create_superuser("root", "r@example.com", "x")
    assert u.role == "admin"


def test_sign_in_is_audited(client, student):
    login(client, student.username)
    assert AuditLog.objects.filter(action="sign_in", user=student).exists()


def test_sidebar_matches_role(client, student, lecturer):
    client.force_login(student)
    assert b"Exam results" in client.get("/student/").content
    client.force_login(lecturer)
    body = client.get("/lecturer/").content
    assert b"Question bank" in body and b"Exam results" not in body


def test_sign_in_page_shows_site_name(client, db):
    # Django's LoginView injects its own `site` variable; our branding must not clash with it.
    r = client.get(reverse("accounts:login"))
    assert r.content.count(b"Lumen") >= 3


def test_sign_in_without_remember_me_ends_with_browser(client, student):
    login(client, student.username)
    assert client.session.get_expire_at_browser_close()


def test_sign_in_with_remember_me_keeps_session(client, student):
    client.post(reverse("accounts:login"), {"username": student.username, "password": PW, "remember": "on"})
    assert not client.session.get_expire_at_browser_close()


def test_first_sign_in_page_is_centred_set_password_screen(client, student):
    student.must_change_password = True
    student.save()
    login(client, student.username)
    r = client.get(reverse("accounts:password-change"))
    assert b"Temporary password" in r.content and b"Save and continue" in r.content
