import pytest
from django.urls import reverse

from apps.courses.models import Course, Enrolment

pytestmark = pytest.mark.django_db


def _setup(django_user_model):
    lec = django_user_model.objects.create_user("lec1", password="x" * 12, role="lecturer", first_name="L", last_name="One")
    stu = django_user_model.objects.create_user("stu1", password="x" * 12, role="student", first_name="S", last_name="One")
    other = django_user_model.objects.create_user("stu2", password="x" * 12, role="student", first_name="O", last_name="Two")
    c = Course.objects.create(code="CS1", title="Intro")
    c.lecturers.add(lec)
    Enrolment.objects.create(course=c, user=stu, status="active")
    Enrolment.objects.create(course=c, user=other, status="active")
    return lec, stu, other


def test_lecturer_sees_progress(client, django_user_model):
    lec, stu, _ = _setup(django_user_model)
    client.force_login(lec)
    r = client.get(reverse("accounts:person", args=[stu.pk]))
    assert r.status_code == 200
    assert b"Course progress" in r.content and b"Assessment results" in r.content


def test_student_does_not_see_classmates_marks(client, django_user_model):
    _, stu, other = _setup(django_user_model)
    client.force_login(stu)
    r = client.get(reverse("accounts:person", args=[other.pk]))
    assert b"Assessment results" not in r.content and b"Average grade" not in r.content
