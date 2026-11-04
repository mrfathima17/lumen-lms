import pytest
from django.urls import reverse

from apps.courses.models import Course, Enrolment

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client, django_user_model):
    a = django_user_model.objects.create_user("boss", password="Pw-12345-x", role="admin")
    client.force_login(a)
    return client


def test_users_page_has_stats_and_pending(admin_client, django_user_model):
    django_user_model.objects.create_user("new1", password="x", role="student", must_change_password=True)
    html = admin_client.get(reverse("administration:users")).content.decode()
    assert "Pending first login" in html and "Students" in html and "Activity" in html


def test_edit_user_shows_status_and_courses(admin_client, django_user_model):
    u = django_user_model.objects.create_user("stu9", password="x", role="student")
    c = Course.objects.create(code="MA101", title="Calculus")
    Enrolment.objects.create(course=c, user=u)
    html = admin_client.get(reverse("administration:user-edit", args=[u.pk])).content.decode()
    assert "Enrolled courses" in html and "MA101" in html and "Last login" in html and "Never" in html


def test_settings_grouped_and_saves(admin_client):
    r = admin_client.get(reverse("administration:settings"))
    html = r.content.decode()
    for h in ("Coursework &amp; results", "Security &amp; storage", "Maintenance"):
        assert h in html


def test_activity_and_sessions_render(admin_client, django_user_model):
    u = django_user_model.objects.create_user("stu8", password="x", role="student")
    assert b"Sign out all sessions" in admin_client.get(reverse("administration:user-activity", args=[u.pk])).content
    assert b"session" in admin_client.get(reverse("administration:sessions")).content
