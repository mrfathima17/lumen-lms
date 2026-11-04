from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.completion.models import CompletionRule
from apps.core.models import ModuleSetting
from apps.courses.models import Course, Enrolment, Topic
from apps.grading.models import GradeItem
from apps.surveys.models import Survey


def login(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def topic(course):
    return Topic.objects.create(course=course, title="ER Modelling", position=1)


def test_course_page_has_tabs_and_student_status(client, course, enrolled, topic):
    Assignment.objects.create(course=course, topic=topic, title="ER Diagram", due_at=timezone.now() + timedelta(days=2))
    Assignment.objects.create(course=course, topic=topic, title="Done one", due_at=timezone.now() + timedelta(days=3))
    Submission.objects.create(assignment=Assignment.objects.get(title="Done one"), student=enrolled, submitted_at=timezone.now())
    CompletionRule.objects.create(course=course, require_assignments=True)
    html = login(client, enrolled).get(reverse("courses:detail", args=[course.pk])).content.decode()
    assert 'class="tabs"' in html and "Participants" in html and "Grades" in html
    assert reverse("grading:my-course-grades", args=[course.pk]) in html
    assert "ER Diagram" in html and "Submitted" in html and "Your progress" in html
    assert 'class="topic"' in html and "Manage this course" not in html


def test_lecturer_sees_manage_card_and_gradebook_tab(client, course, lecturer, topic):
    html = login(client, lecturer).get(reverse("courses:detail", args=[course.pk])).content.decode()
    assert "Manage this course" in html and "Add a topic" in html
    assert reverse("grading:gradebook", args=[course.pk]) in html


def test_survey_listed_and_hidden_when_module_off(client, course, enrolled):
    Survey.objects.create(course=course, title="End of course", is_visible=True)
    url = reverse("courses:detail", args=[course.pk])
    assert "End of course" in login(client, enrolled).get(url).content.decode()
    ModuleSetting.objects.update_or_create(key="surveys", defaults={"enabled": False})
    html = client.get(url).content.decode()
    assert "End of course" not in html


def test_forum_tab_follows_module_switch(client, course, enrolled):
    url = reverse("courses:detail", args=[course.pk])
    assert reverse("messaging:forum", args=[course.pk]) in login(client, enrolled).get(url).content.decode()
    ModuleSetting.objects.update_or_create(key="forums", defaults={"enabled": False})
    assert reverse("messaging:forum", args=[course.pk]) not in client.get(url).content.decode()


def test_my_course_grades(client, course, enrolled):
    GradeItem.objects.create(course=course, title="Midterm", kind="manual", max_mark=Decimal("100"), weight=Decimal("40"))
    html = login(client, enrolled).get(reverse("grading:my-course-grades", args=[course.pk])).content.decode()
    assert "Midterm" in html and "Pending" in html and "40" in html


def test_my_course_grades_needs_enrolment(client, course, student):
    assert login(client, student).get(reverse("grading:my-course-grades", args=[course.pk])).status_code == 404


def test_my_course_grades_is_student_only(client, course, lecturer):
    assert login(client, lecturer).get(reverse("grading:my-course-grades", args=[course.pk])).status_code == 403


def test_catalog_cards(client, course, student):
    course.allow_self_enrol = True
    course.save()
    html = login(client, student).get(reverse("courses:catalog")).content.decode()
    assert 'class="card course"' in html and f"tone-{course.tone}" in html and "Open enrolment" in html


def test_my_courses_shows_progress_for_students(client, course, enrolled):
    CompletionRule.objects.create(course=course, require_assignments=True)
    html = login(client, enrolled).get(reverse("courses:my-courses")).content.decode()
    assert 'class="card course"' in html and "% done" in html


def test_participants_staff_columns_and_export(client, course, enrolled, lecturer):
    GradeItem.objects.create(course=course, title="Midterm", kind="manual", max_mark=Decimal("100"), weight=Decimal("40"))
    CompletionRule.objects.create(course=course, require_assignments=True)
    html = login(client, lecturer).get(reverse("courses:participants", args=[course.pk])).content.decode()
    assert "Progress" in html and "Grade" in html and "Export CSV" in html
    res = client.get(reverse("courses:participants-export", args=[course.pk]))
    assert res.status_code == 200 and res["Content-Type"].startswith("text/csv")
    body = res.content.decode()
    assert body.splitlines()[0].startswith("Name,Username") and enrolled.username in body


def test_participants_students_see_no_marks_and_cannot_export(client, course, enrolled):
    login(client, enrolled)
    html = client.get(reverse("courses:participants", args=[course.pk])).content.decode()
    assert "Progress" not in html and "Export CSV" not in html
    assert client.get(reverse("courses:participants-export", args=[course.pk])).status_code == 403


def test_export_neutralises_formulas(client, course, lecturer, make_user):
    evil = make_user("evil", first_name="=HYPERLINK(1)")
    Enrolment.objects.create(course=course, user=evil)
    body = login(client, lecturer).get(reverse("courses:participants-export", args=[course.pk])).content.decode()
    assert ",=HYPERLINK" not in body and "\n=HYPERLINK" not in body


def test_completion_course_page_lists_other_courses(client, course, enrolled, lecturer):
    other = Course.objects.create(code="MA101", title="Maths")
    other.lecturers.add(lecturer)
    Enrolment.objects.create(course=other, user=enrolled)
    CompletionRule.objects.create(course=course, require_assignments=True)
    CompletionRule.objects.create(course=other, require_assignments=True)
    html = login(client, enrolled).get(reverse("completion:mine-course", args=[course.pk])).content.decode()
    assert "donut" in html and "Other courses" in html and "Maths" in html
