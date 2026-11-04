import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.assignments.models import Assignment, Submission
from apps.completion.models import Certificate
from apps.core.models import AuditLog
from apps.courses.models import Course, Enrolment, Topic
from apps.quizzes.models import Attempt, Quiz

pytestmark = pytest.mark.django_db


def login(client, user):
    client.force_login(user)
    return client


def start(client, course, where="course"):
    return client.post(reverse("courses:preview"), {"course": course.pk, "where": where})


@pytest.fixture
def topic(course):
    return Topic.objects.create(course=course, title="Week 1", position=1)


def test_picker_page_and_start(client, lecturer, course):
    login(client, lecturer)
    assert b"Start a preview" in client.get(reverse("courses:preview")).content
    r = start(client, course)
    assert r.status_code == 302 and r.url == reverse("courses:detail", args=[course.pk])
    assert AuditLog.objects.filter(action="preview_started", target="CS201").exists()


def test_preview_shows_student_view_and_banner(client, lecturer, course, topic):
    Topic.objects.create(course=course, title="Hidden week", position=2, is_visible=False)
    start(login(client, lecturer), course)
    html = client.get(reverse("courses:detail", args=[course.pk])).content.decode()
    assert "Previewing" in html and "Exit preview" in html
    assert "Hidden week" not in html and "Week 1" in html
    assert "Add topic" not in html  # editing tools are not shown
    assert reverse("courses:my-courses") in html and reverse("grading:gradebook-list") not in html  # student menu


def test_preview_is_read_only(client, lecturer, course, topic):
    quiz = Quiz.objects.create(course=course, title="Q1")
    a = Assignment.objects.create(course=course, title="A1", max_mark=100, due_at="2030-01-01T00:00:00Z")
    start(login(client, lecturer), course)
    r = client.post(reverse("quizzes:start", args=[quiz.pk]))
    assert r.status_code == 302 and not Attempt.objects.exists()
    r = client.post(reverse("courses:topic-add", args=[course.pk]), {"title": "Sneaky"})
    assert r.status_code == 302 and not Topic.objects.filter(title="Sneaky").exists()
    assert not Submission.objects.exists() and a.pk


def test_real_account_is_never_changed(client, lecturer, course):
    start(login(client, lecturer), course)
    client.get(reverse("courses:detail", args=[course.pk]))
    client.get(reverse("accounts:student-dashboard"))
    assert User.objects.get(pk=lecturer.pk).role == "lecturer"


def test_no_certificate_for_previewing_lecturer(client, lecturer, course):
    from apps.completion.models import CompletionRule

    CompletionRule.objects.create(course=course, require_assignments=True, auto_certificate=True)
    start(login(client, lecturer), course, "dashboard")
    client.get(reverse("completion:mine-course", args=[course.pk]))
    client.get(reverse("completion:certificates"))
    assert not Certificate.objects.exists()


def test_exit_restores_staff_view(client, lecturer, course):
    start(login(client, lecturer), course)
    r = client.post(reverse("courses:preview-exit"))
    assert r.status_code == 302
    html = client.get(reverse("courses:detail", args=[course.pk])).content.decode()
    assert "Previewing" not in html and reverse("grading:gradebook-list") in html
    assert AuditLog.objects.filter(action="preview_ended").exists()


def test_cannot_preview_someone_elses_course(client, lecturer, make_user, course):
    other = Course.objects.create(code="ZZ9", title="Other")
    login(client, lecturer)
    r = start(client, other)
    assert r.status_code == 302 and r.url == reverse("courses:preview")
    assert "preview_course" not in client.session


def test_students_cannot_use_preview(client, student):
    login(client, student)
    assert client.get(reverse("courses:preview")).status_code == 403
    assert client.post(reverse("courses:preview"), {"course": 1}).status_code == 403


def test_stale_preview_after_losing_the_course(client, lecturer, course):
    start(login(client, lecturer), course)
    course.lecturers.remove(lecturer)
    client.get(reverse("accounts:lecturer-dashboard"))
    assert "preview_course" not in client.session


def test_admin_can_preview_and_sign_out_still_works(client, admin_user, course):
    login(client, admin_user)
    start(client, course)
    assert b"Previewing" in client.get(reverse("courses:detail", args=[course.pk])).content
    assert client.post(reverse("accounts:logout")).status_code == 302
