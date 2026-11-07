"""What a lecturer does in the browser, and what the student then sees as a result."""
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from playwright.sync_api import Page, expect

from apps.assignments.models import Assignment, Submission
from apps.quizzes.models import Quiz

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def assignment(course):
    return Assignment.objects.create(course=course, title="ER Diagram", due_at=timezone.now() + timedelta(days=2), max_mark=100)


@pytest.fixture
def submission(assignment, enrolled):
    return Submission.objects.create(assignment=assignment, student=enrolled, file=SimpleUploadedFile("er.pdf", b"%PDF-1.4 test"),
                                     submitted_at=timezone.now(), status="submitted")


# ---- announcements -----------------------------------------------------------------------------------------------

def test_lecturer_posts_an_announcement_the_student_can_read(page: Page, sign_in, switch_to, url, lecturer, enrolled):
    sign_in(lecturer)
    page.goto(url("messaging:announcement-new"))
    page.get_by_label("Title").fill("Lab moved to room B-204")
    page.get_by_label("Message", exact=True).fill("Thursday's lab is now in B-204.")
    page.get_by_role("button", name="Post announcement").click()

    switch_to(enrolled)
    page.goto(url("messaging:announcements"))
    expect(page.get_by_text("Lab moved to room B-204")).to_be_visible()


def test_a_draft_announcement_is_hidden_from_students(page: Page, sign_in, switch_to, url, lecturer, enrolled):
    sign_in(lecturer)
    page.goto(url("messaging:announcement-new"))
    page.get_by_label("Title").fill("Secret plans")
    page.get_by_label("Message", exact=True).fill("Not ready yet.")
    page.get_by_role("button", name="Save draft").click()

    switch_to(enrolled)
    page.goto(url("messaging:announcements"))
    expect(page.get_by_text("Secret plans")).to_have_count(0)


# ---- marking -----------------------------------------------------------------------------------------------------

def test_lecturer_grades_a_submission_and_the_student_sees_the_feedback(page: Page, sign_in, switch_to, url, lecturer, enrolled, submission, assignment):
    sign_in(lecturer)
    page.goto(url("assignments:grade", submission.pk))
    page.get_by_label("Mark").fill("85")
    page.get_by_label("Feedback").fill("Clear diagram, add cardinalities next time.")
    page.get_by_role("button", name="Save grade", exact=True).click()

    switch_to(enrolled)
    page.goto(url("assignments:detail", assignment.pk))
    expect(page.get_by_text("Submitted & graded")).to_be_visible()
    expect(page.get_by_text("Clear diagram, add cardinalities next time.")).to_be_visible()


def test_a_mark_above_the_maximum_is_refused(page: Page, sign_in, url, lecturer, submission):
    sign_in(lecturer)
    page.goto(url("assignments:grade", submission.pk))
    page.get_by_label("Mark").fill("150")  # the assignment is out of 100
    page.get_by_role("button", name="Save grade", exact=True).click()

    expect(page.get_by_text("The mark cannot be above 100.")).to_be_visible()
    submission.refresh_from_db()
    assert submission.status == "submitted"  # nothing was saved


# ---- creating course content ------------------------------------------------------------------------------------

def test_lecturer_adds_a_topic_to_the_course(page: Page, sign_in, url, lecturer, course):
    sign_in(lecturer)
    page.goto(url("courses:detail", course.pk))
    page.get_by_label("Title").fill("Week 1: Normalisation")
    page.get_by_role("button", name="Add topic").click()
    expect(page.get_by_text("Week 1: Normalisation").first).to_be_visible()


def test_lecturer_creates_a_quiz(page: Page, sign_in, url, lecturer, course):
    sign_in(lecturer)
    page.goto(url("quizzes:new", course.pk))
    page.get_by_label("Title").fill("Midterm quiz")
    page.get_by_label("Time limit minutes").fill("45")
    page.get_by_role("button", name="Save quiz").click()

    expect(page.get_by_text("Midterm quiz").first).to_be_visible()
    quiz = Quiz.objects.get(course=course, title="Midterm quiz")
    assert quiz.time_limit_minutes == 45


def test_lecturer_publishes_an_assignment_students_can_open(page: Page, sign_in, switch_to, url, lecturer, enrolled, course):
    due = (timezone.localtime() + timedelta(days=7)).strftime("%Y-%m-%dT17:00")
    sign_in(lecturer)
    page.goto(url("assignments:new", course.pk))
    page.get_by_label("Title").fill("Normalisation worksheet")
    page.get_by_label("Due date and time").fill(due)
    page.get_by_role("button", name="Publish assignment").click()
    expect(page.get_by_text("Normalisation worksheet").first).to_be_visible()

    switch_to(enrolled)
    page.goto(url("assignments:overview"))
    expect(page.get_by_text("Normalisation worksheet")).to_be_visible()


# ---- attendance --------------------------------------------------------------------------------------------------

def test_lecturer_marks_a_student_absent_and_the_student_sees_it(page: Page, sign_in, switch_to, url, lecturer, enrolled, course):
    sign_in(lecturer)
    page.goto(url("attendance:session-new", course.pk))
    page.get_by_label("Title").fill("Lecture 1")
    page.get_by_label("Held on").fill(timezone.localdate().isoformat())
    page.get_by_role("button", name="Create and take attendance").click()

    page.locator(f"select[name=status_{enrolled.pk}]").select_option("absent")
    page.get_by_role("button", name="Save attendance").last.click()

    switch_to(enrolled)
    page.goto(url("attendance:my-attendance"))
    expect(page.get_by_text("Lecture 1")).to_be_visible()
    expect(page.locator(".pill.bad", has_text="Absent")).to_be_visible()
