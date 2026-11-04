from datetime import time
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.courses.models import Category, Course, Enrolment
from apps.grading.models import CourseResult, GradeBand, GradeItem, ManualMark
from apps.schedule.models import TimetableSlot


def login(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def bands(db):
    GradeBand.objects.all().delete()
    for pct, letter, pts in [(80, "A", "4.0"), (60, "B", "3.0"), (40, "C", "2.0"), (0, "F", "0")]:
        GradeBand.objects.create(min_percent=pct, letter=letter, points=Decimal(pts))


def result(student, course, percent, letter, points, lecturer):
    return CourseResult.objects.create(course=course, student=student, percent=Decimal(percent), letter=letter,
                                       points=Decimal(points), credits=course.credits, published_at=timezone.now(), published_by=lecturer)


def test_grades_page_has_stats_and_summary(client, course, enrolled, lecturer, bands):
    a = GradeItem.objects.create(course=course, title="Midterm", kind="manual", max_mark=Decimal("100"), weight=Decimal("60"))
    GradeItem.objects.create(course=course, title="Final", kind="manual", max_mark=Decimal("100"), weight=Decimal("40"))
    ManualMark.objects.create(item=a, student=enrolled, mark=Decimal("90"))
    html = login(client, enrolled).get(reverse("grading:my-grades")).content.decode()
    assert "Average score" in html and "Graded items" in html and "Pending" in html
    assert "Course summary" in html and "Midterm" in html and "90" in html
    assert "Nimal Perera" in html  # lecturer column


def test_grades_page_empty_state(client, student):
    assert "No courses" in login(client, student).get(reverse("grading:my-grades")).content.decode()


def test_results_tabs_standing_and_scale(client, course, enrolled, lecturer, bands):
    s1 = Category.objects.create(name="Semester 1", kind="semester")
    other = Course.objects.create(code="MA1", title="Maths", semester=s1, credits=3)
    course.semester = Category.objects.create(name="Semester 2", kind="semester")
    course.save()
    result(enrolled, other, "85", "A", "4.0", lecturer)
    result(enrolled, course, "65", "B", "3.0", lecturer)
    url = reverse("grading:my-results")
    html = login(client, enrolled).get(url).content.decode()
    assert "Semester 1" in html and "Semester 2" in html
    assert "Semester GPA" in html and "Cumulative GPA" in html and "Grade scale" in html
    assert "Good standing" in html and "Quality pts" in html and "Database Systems" in html
    first = client.get(url + "?semester=0").content.decode()
    assert "Maths" in first and "Dean&#x27;s list" in first or "Dean's list" in first
    assert client.get(url + "?semester=99").status_code == 200  # out of range falls back to the latest


def test_results_empty(client, student):
    assert "No results yet" in login(client, student).get(reverse("grading:my-results")).content.decode()


def test_attendance_page_shows_limit_marker(client, course, enrolled):
    html = login(client, enrolled).get(reverse("attendance:my-attendance")).content.decode()
    assert 'class="bar80"' in html and "left:80%" in html


def test_timetable_grid(client, course, enrolled, lecturer):
    TimetableSlot.objects.create(course=course, weekday=2, start_time=time(14), end_time=time(16), room="B-204")
    html = login(client, enrolled).get(reverse("schedule:timetable")).content.decode()
    assert 'class="tt"' in html and "B-204" in html and "Up next" in html
    assert "grid-row:14 / span 4" in html


def test_grade_scale_shows_whole_mark_ranges(client, course, enrolled, lecturer, bands):
    result(enrolled, course, "65", "B", "3.0", lecturer)
    html = login(client, enrolled).get(reverse("grading:my-results")).content.decode()
    assert "80–100" in html and "60–79" in html and "0–39" in html
