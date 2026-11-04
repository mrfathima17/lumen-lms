from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.core.models import AuditLog
from apps.grading.models import GradeBand, GradeItem
from apps.quizzes.models import Answer, Attempt, Choice, Question, Quiz


def login(client, user):
    client.force_login(user)
    return client


def test_lecturer_changes_settings_but_not_code(client, lecturer, course):
    login(client, lecturer)
    r = client.get(reverse("courses:settings", args=[course.pk]))
    assert r.status_code == 200 and b"Course visible to students" in r.content
    r = client.post(reverse("courses:settings", args=[course.pk]), {"title": "Databases II", "summary": "x", "credits": 4, "allow_self_enrol": "on", "enrol_key": "KEY1", "code": "HACK"})
    assert r.status_code == 302
    course.refresh_from_db()
    assert course.title == "Databases II" and course.allow_self_enrol and course.enrol_key == "KEY1"
    assert course.code == "CS201" and not course.is_visible  # unchecked box means hidden
    assert AuditLog.objects.filter(action="course_updated", target="CS201").exists()


def test_settings_and_reports_are_for_staff_only(client, student, enrolled, make_user, course):
    other = make_user("lect2", "lecturer")
    for who in (student, other):
        login(client, who)
        assert client.get(reverse("courses:settings", args=[course.pk])).status_code == 403
        assert client.get(reverse("courses:reports", args=[course.pk])).status_code == 403
    client.logout()
    assert client.get(reverse("courses:reports", args=[course.pk])).status_code == 302


def test_tabs_show_for_staff_only(client, lecturer, enrolled, course):
    login(client, lecturer)
    assert reverse("courses:reports", args=[course.pk]).encode() in client.get(reverse("courses:detail", args=[course.pk])).content
    login(client, enrolled)
    assert reverse("courses:reports", args=[course.pk]).encode() not in client.get(reverse("courses:detail", args=[course.pk])).content


def test_reports_empty_course_renders(client, lecturer, course):
    login(client, lecturer)
    r = client.get(reverse("courses:reports", args=[course.pk]))
    assert r.status_code == 200 and b"Nobody is flagged" in r.content


def test_reports_figures(client, lecturer, enrolled, course, make_user):
    from apps.courses.models import Enrolment

    low = make_user("s-low", "student")
    Enrolment.objects.create(course=course, user=low)
    GradeBand.objects.all().delete()
    GradeBand.objects.create(min_percent=Decimal("0"), letter="F", points=Decimal("0"))
    GradeBand.objects.create(min_percent=Decimal("50"), letter="C", points=Decimal("2"))
    GradeBand.objects.create(min_percent=Decimal("75"), letter="A", points=Decimal("4"))
    a = Assignment.objects.create(course=course, title="A1", max_mark=100, due_at=timezone.now() + timedelta(days=3), created_by=lecturer) \
        if "created_by" in [f.name for f in Assignment._meta.fields] else Assignment.objects.create(course=course, title="A1", max_mark=100, due_at=timezone.now() + timedelta(days=3))
    GradeItem.objects.create(course=course, kind="assignment", title="A1", assignment=a, weight=100, max_mark=100)
    for stu, mark in ((enrolled, 90), (low, 30)):
        Submission.objects.create(assignment=a, student=stu, file="x.txt", submitted_at=timezone.now(), status="graded", raw_mark=mark, final_mark=mark)
    login(client, lecturer)
    r = client.get(reverse("courses:reports", args=[course.pk]))
    html = r.content.decode()
    assert r.status_code == 200
    assert "60.0%" in html or "60%" in html  # average of 90 and 30
    assert "s-low" in html and "Karunaratne" not in html.split("Students at risk")[1]
    assert "A · 1" in html and "C · 0" in html


def test_most_missed_needs_three_answers(client, lecturer, course, make_user):
    from apps.courses.models import Enrolment

    quiz = Quiz.objects.create(course=course, title="Q1")
    q = Question.objects.create(quiz=quiz, text="Which is a transitive dependency?", marks=1)
    Choice.objects.create(question=q, text="a", is_correct=True)
    for i in range(3):
        u = make_user(f"qs{i}", "student")
        Enrolment.objects.create(course=course, user=u)
        at = Attempt.objects.create(quiz=quiz, student=u, started_at=timezone.now(), submitted_at=timezone.now(), status="graded", score=Decimal("1" if i == 0 else "0"))
        Answer.objects.create(attempt=at, question=q, awarded=Decimal("1" if i == 0 else "0"))
    login(client, lecturer)
    html = client.get(reverse("courses:reports", args=[course.pk])).content.decode()
    assert "transitive dependency" in html and "33%" in html


def test_sidebar_tools_pick_a_course(client, lecturer, course, make_user):
    from apps.courses.models import Course

    login(client, lecturer)
    # one course: straight through
    r = client.get(reverse("courses:tool-reports"))
    assert r.status_code == 302 and r.url == reverse("courses:reports", args=[course.pk])
    assert client.get(reverse("courses:tool-settings")).url == reverse("courses:settings", args=[course.pk])
    assert client.get(reverse("courses:tool-add-material")).url == reverse("content:add", args=[course.pk])
    c2 = Course.objects.create(code="CS300", title="Networks")
    c2.lecturers.add(lecturer)
    r = client.get(reverse("courses:tool-reports"))
    assert r.status_code == 200 and b"CS300" in r.content and b"CS201" in r.content
    page = client.get(reverse("accounts:lecturer-dashboard")).content
    assert reverse("courses:tool-reports").encode() in page and reverse("courses:tool-settings").encode() in page


def test_sidebar_tools_not_for_students(client, student):
    login(client, student)
    assert client.get(reverse("courses:tool-reports")).status_code == 403
