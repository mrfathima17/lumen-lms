import pytest
from django.urls import reverse

from apps.completion.models import CompletionRule
from apps.courses.models import Course, Enrolment

pytestmark = pytest.mark.django_db


def test_public_home_shows_stats_and_courses(client):
    Course.objects.create(code="CS101", title="Intro Programming")
    Course.objects.create(code="HID1", title="Hidden thing", is_visible=False)
    r = client.get(reverse("core:public-home"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "Intro Programming" in html and "Hidden thing" not in html
    assert "Course catalog" in html and "Active courses" in html


def test_password_change_has_strength_rules(client, django_user_model):
    u = django_user_model.objects.create_user("stu1", password="Old-pass-123", role="student")
    client.force_login(u)
    r = client.get(reverse("accounts:password-change"))
    assert r.status_code == 200 and b'id="pw-rules"' in r.content


def test_certificates_lists_in_progress(client, django_user_model):
    u = django_user_model.objects.create_user("stu2", password="x-Pass-123", role="student")
    c = Course.objects.create(code="DB201", title="Databases")
    Enrolment.objects.create(course=c, user=u)
    CompletionRule.objects.create(course=c, require_assignments=True)
    client.force_login(u)
    r = client.get(reverse("completion:certificates"))
    assert r.status_code == 200
    assert b"Complete the course to unlock" in r.content and b"In progress" in r.content
