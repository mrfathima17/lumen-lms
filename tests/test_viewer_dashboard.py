import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from apps.content.models import Resource
from apps.courses.models import Topic

pytestmark = pytest.mark.django_db


def login(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def topic(course):
    return Topic.objects.create(course=course, title="ER Modelling", position=1)


def file_res(topic, name, data=b"%PDF-1.4 test", **kw):
    r = Resource(topic=topic, kind="file", title=kw.pop("title", name), **kw)
    r.file.save(name, ContentFile(data), save=True)
    return r


def test_pdf_preview_is_inline_and_framable(client, enrolled, topic):
    r = file_res(topic, "lecture.pdf", title="Lecture 3")
    login(client, enrolled)
    page = client.get(reverse("content:view", args=[r.pk]))
    assert page.status_code == 200 and b"<object" in page.content and b"Lecture 3" in page.content
    raw = client.get(reverse("content:raw", args=[r.pk]))
    assert raw.status_code == 200 and raw["Content-Disposition"].startswith("inline") and raw["X-Content-Type-Options"] == "nosniff"
    assert raw.get("X-Frame-Options") == "SAMEORIGIN"
    dl = client.get(reverse("content:download", args=[r.pk]))
    assert dl["Content-Disposition"].startswith("attachment")


def test_unsafe_types_never_inline(client, enrolled, topic):
    r = file_res(topic, "notes.txt", b"hello")
    login(client, enrolled)
    assert client.get(reverse("content:raw", args=[r.pk])).status_code == 404
    page = client.get(reverse("content:view", args=[r.pk]))
    assert b"cannot be shown in the browser" in page.content and b"<object" not in page.content


def test_link_resource_page(client, enrolled, topic):
    r = Resource.objects.create(topic=topic, kind="link", title="Docs", url="https://example.com/x")
    login(client, enrolled)
    assert b"https://example.com/x" in client.get(reverse("content:view", args=[r.pk])).content
    assert client.get(reverse("content:raw", args=[r.pk])).status_code == 404


def test_viewer_respects_access_and_hidden(client, student, enrolled, topic, make_user, lecturer):
    r = file_res(topic, "a.pdf", is_visible=False)
    outsider = make_user("out", "student")
    login(client, outsider)
    assert client.get(reverse("content:view", args=[r.pk])).status_code == 403
    assert client.get(reverse("content:raw", args=[r.pk])).status_code == 403
    login(client, enrolled)
    assert client.get(reverse("content:view", args=[r.pk])).status_code == 403  # hidden from students
    login(client, lecturer)
    assert client.get(reverse("content:view", args=[r.pk])).status_code == 200


def test_course_page_links_to_viewer(client, enrolled, topic, course):
    r = file_res(topic, "a.pdf")
    login(client, enrolled)
    assert reverse("content:view", args=[r.pk]).encode() in client.get(reverse("courses:detail", args=[course.pk])).content


# ---- dashboard layout

def test_default_dashboard_shows_everything(client, enrolled):
    login(client, enrolled)
    html = client.get(reverse("accounts:student-dashboard")).content.decode()
    for h in ("My courses", "Upcoming deadlines", "Announcements", "Today's classes", "Course progress", "Enrolled courses"):
        assert h in html


def test_hide_and_reorder_blocks(client, enrolled):
    login(client, enrolled)
    r = client.post(reverse("accounts:customise-dashboard"), {"order": ["announcements", "stats", "courses", "deadlines", "today", "progress"], "show": ["announcements", "stats", "courses"]})
    assert r.status_code == 302
    enrolled.refresh_from_db()
    assert enrolled.dashboard_layout["hidden"] == ["deadlines", "today", "progress"]
    html = client.get(reverse("accounts:student-dashboard")).content.decode()
    assert "Upcoming deadlines" not in html and "Today's classes" not in html
    assert html.index("Announcements") < html.index("Enrolled courses")


def test_move_button_and_reset(client, enrolled):
    login(client, enrolled)
    base = ["stats", "courses", "deadlines", "announcements", "today", "progress"]
    client.post(reverse("accounts:customise-dashboard"), {"order": base, "show": base, "move": "courses:up"})
    enrolled.refresh_from_db()
    assert enrolled.dashboard_layout["order"][:2] == ["courses", "stats"]
    client.post(reverse("accounts:customise-dashboard"), {"reset": "1"})
    enrolled.refresh_from_db()
    assert enrolled.dashboard_layout == {}


def test_hiding_all_shows_hint_and_bad_ids_ignored(client, enrolled):
    login(client, enrolled)
    client.post(reverse("accounts:customise-dashboard"), {"order": ["nope", "stats"], "show": []})
    assert b"Everything is hidden" in client.get(reverse("accounts:student-dashboard")).content
    assert client.get(reverse("accounts:customise-dashboard")).status_code == 200


def test_customise_is_student_only(client, lecturer):
    login(client, lecturer)
    assert client.get(reverse("accounts:customise-dashboard")).status_code == 403


def test_extensions_list_for_staff(client, lecturer, enrolled, course):
    from datetime import timedelta

    from django.utils import timezone

    from apps.assignments.models import Assignment, Extension

    a = Assignment.objects.create(course=course, title="Mini project", max_mark=100, due_at=timezone.now() + timedelta(days=2))
    Extension.objects.create(assignment=a, student=enrolled, due_at=timezone.now() + timedelta(days=5))
    login(client, lecturer)
    html = client.get(reverse("assignments:extensions-list")).content.decode()
    assert "Mini project" in html and reverse("assignments:extensions", args=[a.pk]) in html
    login(client, enrolled)
    assert client.get(reverse("assignments:extensions-list")).status_code == 403


def test_completion_page_lists_activities_with_ticks(client, db):
    from django.contrib.auth import get_user_model
    from apps.content.models import Resource, ResourceDone
    from apps.courses.models import Course, Enrolment, Topic

    U = get_user_model()
    stu = U.objects.create_user("cstu", password="x" * 12, role="student")
    course = Course.objects.create(code="CC1", title="Check")
    Enrolment.objects.create(course=course, user=stu, status="active")
    t = Topic.objects.create(course=course, title="Week 1")
    r = Resource.objects.create(topic=t, kind="link", title="Reading", url="https://example.com")
    client.force_login(stu)
    url = reverse("completion:mine-course", args=[course.pk])
    assert b"Reading" in client.get(url).content and b"Tick when you have finished it" in client.get(url).content
    resp = client.post(reverse("content:done", args=[r.pk]), {"back": "completion"})
    assert resp.status_code == 302 and resp["Location"] == url and ResourceDone.objects.filter(user=stu, resource=r).exists()
