"""What a student does in the browser: take a quiz, hand in work, enrol, plan, write and message."""
import re
from datetime import timedelta

import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from apps.assignments.models import Assignment, Submission
from apps.courses.models import Enrolment
from apps.quizzes.models import Choice, Question, Quiz

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def quiz(course):
    """A one-question multiple-choice quiz: 2 + 2 (worth 2 marks)."""
    qz = Quiz.objects.create(course=course, title="Quiz 1", time_limit_minutes=30, max_attempts=2)
    q = Question.objects.create(quiz=qz, kind="mcq", text="2+2?", marks=2, position=0)
    Choice.objects.create(question=q, text="3", position=0)
    Choice.objects.create(question=q, text="4", is_correct=True, position=1)
    return qz


@pytest.fixture
def assignment(course):
    return Assignment.objects.create(course=course, title="ER Diagram", due_at=timezone.now() + timedelta(days=2), max_mark=100)


# ---- quizzes ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("answer, score", [("4", "2/2"), ("3", "0/2")])
def test_student_takes_a_quiz_and_sees_the_score(page: Page, sign_in, url, enrolled, quiz, answer, score):
    sign_in(enrolled)
    page.goto(url("quizzes:student-detail", quiz.pk))
    page.get_by_label("I have read the instructions.").check()  # the Start button stays disabled until this is ticked
    page.get_by_role("button", name="Start attempt").click()

    with page.expect_response("**/answer/**"):  # each answer is saved in the background as soon as it is chosen
        page.get_by_label(answer, exact=True).check()
    page.once("dialog", lambda d: d.accept())  # "Submit your answers now?" confirmation
    page.get_by_role("button", name="Finish attempt").click()

    expect(page.get_by_role("heading", name="Quiz 1 · Result")).to_be_visible()
    expect(page.locator(".donut-inner")).to_have_text(score)


def test_start_button_is_disabled_until_instructions_are_read(page: Page, sign_in, url, enrolled, quiz):
    sign_in(enrolled)
    page.goto(url("quizzes:student-detail", quiz.pk))
    start = page.get_by_role("button", name="Start attempt")
    expect(start).to_be_disabled()
    page.get_by_label("I have read the instructions.").check()
    expect(start).to_be_enabled()


# ---- assignments -----------------------------------------------------------------------------------------------

def test_student_submits_an_assignment(page: Page, sign_in, url, enrolled, assignment):
    sign_in(enrolled)
    page.goto(url("assignments:detail", assignment.pk))
    expect(page.get_by_text("You have not submitted yet.")).to_be_visible()

    page.locator("input[name=file]").set_input_files({"name": "er-diagram.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 test"})
    page.get_by_label("I confirm this is my own work.").check()
    page.get_by_role("button", name="Submit assignment").click()

    expect(page.get_by_text("er-diagram.pdf")).to_be_visible()
    expect(page.get_by_text("Awaiting grading")).to_be_visible()
    assert Submission.objects.filter(assignment=assignment, student=enrolled).count() == 1


def test_assignment_cannot_be_submitted_without_the_own_work_confirmation(page: Page, sign_in, url, enrolled, assignment):
    sign_in(enrolled)
    page.goto(url("assignments:detail", assignment.pk))
    page.locator("input[name=file]").set_input_files({"name": "er-diagram.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 test"})
    page.get_by_role("button", name="Submit assignment").click()  # the box is not ticked

    expect(page.get_by_text("You have not submitted yet.")).to_be_visible()
    assert Submission.objects.filter(assignment=assignment).count() == 0


# ---- enrolment -------------------------------------------------------------------------------------------------

def test_student_enrols_in_a_course_with_the_right_key(page: Page, sign_in, url, course, student):
    course.allow_self_enrol, course.enrol_key = True, "KEY1"
    course.save()
    sign_in(student)
    page.goto(url("courses:catalog"))

    page.get_by_role("button", name="Enrol").click()
    page.locator("dialog[open] input[name=key]").fill("KEY1")
    page.locator("dialog[open]").get_by_role("button", name="Enrol").click()

    expect(page.get_by_text("You are enrolled")).to_be_visible()
    assert Enrolment.objects.filter(course=course, user=student).exists()


def test_wrong_enrolment_key_is_refused(page: Page, sign_in, url, course, student):
    course.allow_self_enrol, course.enrol_key = True, "KEY1"
    course.save()
    sign_in(student)
    page.goto(url("courses:catalog"))

    page.get_by_role("button", name="Enrol").click()
    page.locator("dialog[open] input[name=key]").fill("WRONG")
    page.locator("dialog[open]").get_by_role("button", name="Enrol").click()

    assert not Enrolment.objects.filter(course=course, user=student).exists()


# ---- planning, writing, messaging ------------------------------------------------------------------------------

def test_student_adds_a_todo_item_and_ticks_it_off(page: Page, sign_in, url, student):
    sign_in(student)
    page.goto(url("schedule:todo"))
    page.get_by_role("button", name="Add personal task").click()  # the form is hidden until this is clicked
    page.get_by_label("Task").fill("Revise normalisation")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_text("Revise normalisation")).to_be_visible()

    page.get_by_label("Mark done: Revise normalisation").check()  # ticking submits straight away
    expect(page.get_by_label("Mark not done: Revise normalisation")).to_be_checked()


def test_student_adds_a_calendar_event(page: Page, sign_in, url, student):
    sign_in(student)
    page.goto(url("schedule:event-new"))
    today_evening = timezone.localtime().strftime("%Y-%m-%dT23:30")  # today, so it shows on the current month's calendar
    page.get_by_label("Title").fill("Study group")
    page.get_by_label("Starts").fill(today_evening)
    page.get_by_role("button", name="Add event").click()
    page.goto(url("schedule:calendar"))
    expect(page.get_by_text("Study group").first).to_be_visible()


def test_student_posts_a_forum_topic(page: Page, sign_in, url, enrolled, course):
    sign_in(enrolled)
    page.goto(url("messaging:topic-new", course.pk))
    page.get_by_label("Title").fill("Help with joins")
    page.get_by_label("Your post").fill("When do I use a LEFT JOIN instead of an INNER JOIN?")
    page.get_by_role("button", name="Post topic").click()
    expect(page.get_by_text("Help with joins").first).to_be_visible()
    expect(page.get_by_text("LEFT JOIN instead of an INNER JOIN")).to_be_visible()


def test_student_messages_a_lecturer_who_then_receives_it(page: Page, sign_in, switch_to, url, enrolled, lecturer):
    sign_in(enrolled)  # students can only message people from their own courses
    page.goto(url("messaging:compose"))
    page.get_by_label("To", exact=True).select_option(value=str(lecturer.pk))
    page.get_by_label("Subject").fill("Question about the project")
    page.get_by_label("Message", exact=True).fill("Could I get an extension until Friday?")
    page.get_by_role("button", name="Send").click()

    switch_to(lecturer)
    page.goto(url("messaging:inbox"))
    page.get_by_text("Question about the project").first.click()
    expect(page.get_by_text("Could I get an extension until Friday?")).to_be_visible()
