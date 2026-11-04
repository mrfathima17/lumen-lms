from datetime import date, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import ProfileField, ProfileValue
from apps.core import modules
from apps.core.models import AuditLog, ModuleSetting
from apps.courses.models import Enrolment


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def as_user(u):
    c = Client()
    c.force_login(u)
    return c


PAGES = ["modules", "profile-fields", "activity", "bulk-enrolment"]


@pytest.mark.parametrize("name", PAGES)
def test_pages_admin_only(admin_client, student, lecturer, name):
    assert admin_client.get(reverse(f"administration:{name}")).status_code == 200
    for u in (student, lecturer):
        assert as_user(u).get(reverse(f"administration:{name}")).status_code == 403
    assert Client().get(reverse(f"administration:{name}")).status_code == 302


# ---------- modules ----------

def test_switching_a_module_off_blocks_pages_and_hides_menu(admin_client, student, lecturer):
    s = as_user(student)
    assert s.get(reverse("quizzes:student-list")).status_code == 200
    assert b"Quizzes" in s.get(reverse("accounts:student-dashboard")).content
    admin_client.post(reverse("administration:modules"), {"enabled": [k for k in modules.MODULES if k != "quizzes"]})
    assert ModuleSetting.objects.get(key="quizzes").enabled is False
    r = s.get(reverse("quizzes:student-list"))
    assert r.status_code == 404 and b"switched off" in r.content
    assert reverse("quizzes:student-list").encode() not in s.get(reverse("accounts:student-dashboard")).content
    assert as_user(lecturer).get(reverse("quizzes:manage-list")).status_code == 404
    assert AuditLog.objects.filter(action="modules_changed", detail__contains="quizzes off").exists()
    # the admin area is never gated, so it can be switched back on
    admin_client.post(reverse("administration:modules"), {"enabled": list(modules.MODULES)})
    assert s.get(reverse("quizzes:student-list")).status_code == 200


@pytest.mark.parametrize("key,url", [("attendance", "/attendance/"), ("schedule", "/calendar/"), ("schedule", "/timetable/"), ("forums", "/forums/"), ("files", "/files/")])
def test_each_module_gate(student, key, url):
    ModuleSetting.objects.create(key=key, enabled=False)
    assert as_user(student).get(url).status_code == 404


def test_other_modules_stay_on(admin_client, student):
    ModuleSetting.objects.create(key="files", enabled=False)
    s = as_user(student)
    assert s.get("/messages/").status_code == 200 and s.get("/calendar/").status_code == 200


def test_course_page_hides_buttons_of_disabled_modules(course, lecturer):
    ModuleSetting.objects.create(key="attendance", enabled=False)
    html = as_user(lecturer).get(reverse("courses:detail", args=[course.pk])).content
    assert reverse("attendance:course", args=[course.pk]).encode() not in html
    assert reverse("schedule:course-timetable", args=[course.pk]).encode() in html


def test_module_for_url_name():
    assert modules.module_for_url_name("quizzes:manage-list") == "quizzes"
    assert modules.module_for_url_name("messaging:forums") == "forums"
    assert modules.module_for_url_name("messaging:topic-new") == "forums"
    assert modules.module_for_url_name("messaging:inbox") is None
    assert modules.module_for_url_name(None) is None


def test_modules_unknown_key_ignored(admin_client):
    admin_client.post(reverse("administration:modules"), {"enabled": ["quizzes", "evil"]})
    assert not ModuleSetting.objects.filter(key="evil").exists()


# ---------- profile fields ----------

def add_field(client, **kw):
    data = {"label": "Hostel", "key": "hostel", "kind": "text", "applies_to": "all", "position": 0, "is_active": "on"}
    data.update(kw)
    return client.post(reverse("administration:profile-fields"), data)


def test_add_edit_delete_field(admin_client, student):
    assert add_field(admin_client).status_code == 302
    f = ProfileField.objects.get()
    ProfileValue.objects.create(user=student, field=f, value="Block A")
    admin_client.post(reverse("administration:profile-field", args=[f.pk]), {"label": "Hostel name", "key": "hostel", "kind": "text", "applies_to": "student", "position": 1, "is_active": "on"})
    f.refresh_from_db()
    assert f.label == "Hostel name" and f.applies_to == "student"
    admin_client.post(reverse("administration:profile-field-delete", args=[f.pk]))
    assert not ProfileField.objects.exists() and not ProfileValue.objects.exists()
    assert AuditLog.objects.filter(action="profile_field_deleted", detail__contains="1 stored").exists()


@pytest.mark.parametrize("kw", [{"key": "username"}, {"key": "Bad Key!"}, {"kind": "choice", "choices": "only one"}, {"kind": "choice", "choices": "a\nA"}])
def test_bad_field_definitions_rejected(admin_client, kw):
    assert add_field(admin_client, **kw).status_code == 200 and not ProfileField.objects.exists()


def test_duplicate_key_rejected(admin_client):
    add_field(admin_client)
    assert add_field(admin_client, label="Other").status_code == 200 and ProfileField.objects.count() == 1


def test_values_saved_on_user_page_and_validated(admin_client, student):
    add_field(admin_client)
    add_field(admin_client, label="Year", key="year", kind="number")
    add_field(admin_client, label="Joined", key="joined", kind="date")
    add_field(admin_client, label="Meal", key="meal", kind="choice", choices="Veg\nNon-veg")
    f = {x.key: x for x in ProfileField.objects.all()}
    base = {"username": student.username, "first_name": "Amal", "last_name": "K", "email": "", "role": "student", "index_number": student.index_number or "", "faculty": ""}
    url = reverse("administration:user-edit", args=[student.pk])
    r = admin_client.post(url, base | {f"f_{f['hostel'].pk}": "Block A", f"f_{f['year'].pk}": "3", f"f_{f['joined'].pk}": "2025-02-01", f"f_{f['meal'].pk}": "Veg"})
    assert r.status_code == 302
    vals = {v.field.key: v.value for v in ProfileValue.objects.filter(user=student)}
    assert vals == {"hostel": "Block A", "year": "3", "joined": "2025-02-01", "meal": "Veg"}
    assert b"Block A" in admin_client.get(url).content
    # invalid choice and number are refused and nothing changes
    r = admin_client.post(url, base | {f"f_{f['hostel'].pk}": "Block B", f"f_{f['year'].pk}": "abc", f"f_{f['meal'].pk}": "Pizza"})
    assert r.status_code == 200 and ProfileValue.objects.get(user=student, field=f["hostel"]).value == "Block A"
    # blank removes the value
    admin_client.post(url, base | {f"f_{f['hostel'].pk}": ""})
    assert not ProfileValue.objects.filter(user=student, field=f["hostel"]).exists()


def test_required_and_role_scoping(admin_client, student, lecturer):
    add_field(admin_client, required="on", applies_to="student")
    f = ProfileField.objects.get()
    base = {"username": student.username, "first_name": "A", "last_name": "B", "email": "", "role": "student", "index_number": "", "faculty": ""}
    assert admin_client.post(reverse("administration:user-edit", args=[student.pk]), base).status_code == 200  # required, missing
    lbase = base | {"username": lecturer.username, "role": "lecturer"}
    assert admin_client.post(reverse("administration:user-edit", args=[lecturer.pk]), lbase).status_code == 302  # not for lecturers


def test_users_export_includes_custom_columns_safely(admin_client, student):
    add_field(admin_client)
    f = ProfileField.objects.get()
    ProfileValue.objects.create(user=student, field=f, value="=1+1")
    body = admin_client.get(reverse("administration:users-export")).content.decode()
    assert body.splitlines()[0].endswith(",hostel") and "'=1+1" in body


# ---------- user activity ----------

def test_activity_timeline_merges_sources(admin_client, enrolled, course, lecturer):
    from apps.assignments.models import Assignment, Submission
    from apps.messaging.models import Message

    a = Assignment.objects.create(course=course, title="Lab 1", due_at=timezone.now() + timedelta(days=1), max_mark=100)
    Submission.objects.create(assignment=a, student=enrolled, file="x.pdf", submitted_at=timezone.now())
    Message.objects.create(sender=enrolled, recipient=lecturer, subject="Question", body="hi")
    AuditLog.objects.create(user=enrolled, action="sign_in")
    r = admin_client.get(reverse("administration:user-activity", args=[enrolled.pk]))
    html = r.content.decode()
    assert "Submitted Lab 1" in html and "Sent a message: Question" in html and "Signed in" in html


def test_activity_search(admin_client, student, lecturer):
    r = admin_client.get(reverse("administration:activity"), {"q": "nperera"})
    assert b"nperera" in r.content and student.username.encode() not in r.content


# ---------- bulk enrolment ----------

def test_bulk_enrolment_validation(admin_client, course):
    assert admin_client.post(reverse("administration:bulk-enrolment"), {"course": course.pk, "identifiers": "  "}).status_code == 200
    big = " ".join(f"u{i}" for i in range(1001))
    assert b"more than 1000" in admin_client.post(reverse("administration:bulk-enrolment"), {"course": course.pk, "identifiers": big}).content


@pytest.mark.parametrize("app,key", [("quizzes", "quizzes"), ("attendance", "attendance"), ("schedule", "schedule"), ("files", "files")])
def test_every_page_of_a_module_is_gated(app, key):
    """If someone adds a URL to a module's urls.py outside the gated prefixes, this fails."""
    import importlib
    import re

    mod = importlib.import_module(f"apps.{app}.urls")
    for p in mod.urlpatterns:
        path = "/" + re.sub(r"<[^>]+>", "1", str(p.pattern))
        assert modules.module_for_path(path) == key, f"{path} is not covered by the {key} switch"


def test_every_forum_page_is_gated():
    import re

    from apps.messaging import urls as mu

    for p in mu.urlpatterns:
        path = "/" + re.sub(r"<[^>]+>", "1", str(p.pattern))
        if p.name and ("forum" in p.name or "topic" in p.name or "post" in p.name):
            assert modules.module_for_path(path) == "forums", path
