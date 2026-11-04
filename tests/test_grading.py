from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.assignments import services as asg
from apps.assignments.models import Assignment
from apps.courses.models import Category, Course, Enrolment
from apps.grading import services
from apps.grading.models import CourseResult, GradeBand, GradeItem, ManualMark
from apps.quizzes import services as qz
from apps.quizzes.models import Choice, Question, Quiz

D = Decimal


@pytest.fixture
def assignment(course):
    return Assignment.objects.create(course=course, title="A1", due_at=timezone.now() + timedelta(days=2), max_mark=100)


@pytest.fixture
def quiz(course):
    q = Quiz.objects.create(course=course, title="Q1", max_attempts=3)
    mcq = Question.objects.create(quiz=q, kind="mcq", text="x", marks=10)
    Choice.objects.create(question=mcq, text="ok", is_correct=True)
    Choice.objects.create(question=mcq, text="no")
    return q


def do_quiz(quiz, student, right):
    a = qz.start_attempt(quiz, student)
    q = quiz.questions.get()
    qz.save_answer(a, q, choice_id=q.choices.get(is_correct=right).pk)
    return qz.finish_attempt(a)


def submit_and_grade(assignment, student, lecturer, mark, now=None):
    s = asg.submit(assignment, student, SimpleUploadedFile("a.pdf", b"x"), now=now)
    return asg.grade(s, mark, "", lecturer)


# ---------- scale ----------

def test_default_scale_present_and_band_lookup(db):
    assert GradeBand.objects.count() == 12
    assert services.band_for(D("85")).letter == "A+"
    assert services.band_for(D("84.99")).letter == "A"
    assert services.band_for(D("0")).letter == "E"
    assert services.band_for(D("49.5")).letter == "C"


# ---------- percentage maths ----------

def test_weighted_percent_over_graded_items_only(course, enrolled, student, lecturer, assignment, quiz):
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=40)
    GradeItem.objects.create(course=course, title="Q1", kind="quiz", quiz=quiz, weight=20)
    exam = GradeItem.objects.create(course=course, title="Exam", kind="manual", max_mark=50, weight=40)
    items = list(course.grade_items.all())
    fr = services.load_fractions(course, [student.pk])
    assert services.course_percent(items, fr, student.pk)[0] is None  # nothing graded yet
    submit_and_grade(assignment, student, lecturer, 80)
    pct, gw, tw = services.course_percent(items, services.load_fractions(course, [student.pk]), student.pk)
    assert pct == D("80.00") and gw == 40 and tw == 100  # only the assignment counts so far
    do_quiz(quiz, student, True)
    ManualMark.objects.create(item=exam, student=student, mark=25)
    pct, gw, tw = services.course_percent(items, services.load_fractions(course, [student.pk]), student.pk)
    assert pct == D("72.00") and gw == 100  # 0.8*40 + 1.0*20 + 0.5*40


def test_weighted_percent_value(course, enrolled, student, lecturer, assignment, quiz):
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=40)
    GradeItem.objects.create(course=course, title="Q1", kind="quiz", quiz=quiz, weight=20)
    exam = GradeItem.objects.create(course=course, title="Exam", kind="manual", max_mark=50, weight=40)
    submit_and_grade(assignment, student, lecturer, 80)
    do_quiz(quiz, student, True)
    ManualMark.objects.create(item=exam, student=student, mark=25)
    items = list(course.grade_items.all())
    pct = services.course_percent(items, services.load_fractions(course, [student.pk]), student.pk)[0]
    assert pct == D("72.00")  # 80*0.4 + 100*0.2 + 50*0.4


def test_late_penalty_flows_into_gradebook(course, enrolled, student, lecturer, assignment):
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=100)
    submit_and_grade(assignment, student, lecturer, 80, now=assignment.due_at + timedelta(days=1, hours=1))  # 2 days late = 20%
    summary = services.student_course_summary(course, student)
    assert summary["percent"] == D("64.00")


def test_best_quiz_attempt_counts_and_ungraded_attempts_do_not(course, enrolled, student, quiz):
    GradeItem.objects.create(course=course, title="Q1", kind="quiz", quiz=quiz, weight=100)
    do_quiz(quiz, student, False)
    do_quiz(quiz, student, True)
    assert services.student_course_summary(course, student)["percent"] == D("100.00")
    Question.objects.create(quiz=quiz, kind="essay", text="manual", marks=10)  # makes a pending attempt impossible to grade fully
    # an in-progress attempt must never leak into the gradebook
    q2 = Quiz.objects.create(course=course, title="Q2", max_attempts=1)
    mcq = Question.objects.create(quiz=q2, kind="mcq", text="y", marks=5)
    Choice.objects.create(question=mcq, text="a", is_correct=True)
    GradeItem.objects.create(course=course, title="Q2", kind="quiz", quiz=q2, weight=50)
    qz.start_attempt(q2, student)
    items = list(course.grade_items.all())
    fr = services.load_fractions(course, [student.pk])
    assert not any(k[0] == items[1].pk for k in fr)


def test_ungraded_assignment_ignored(course, enrolled, student, assignment):
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=100)
    asg.submit(assignment, student, SimpleUploadedFile("a.pdf", b"x"))  # submitted, not graded
    assert services.student_course_summary(course, student)["percent"] is None


# ---------- publishing and GPA ----------

def test_publish_freezes_results(course, enrolled, student, lecturer, assignment):
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=100)
    submit_and_grade(assignment, student, lecturer, 76)
    published, skipped = services.publish_results(course, lecturer)
    assert (published, skipped) == (1, [])
    r = CourseResult.objects.get()
    assert (r.percent, r.letter, r.points, r.credits) == (D("76.00"), "A", D("4.00"), 4)
    # changing the scale or the mark later does not touch the published result until it is published again
    GradeBand.objects.filter(letter="A").update(points=D("3.50"))
    r.refresh_from_db()
    assert r.points == D("4.00")


def test_students_without_marks_are_skipped(course, enrolled, student, lecturer, assignment, make_user):
    other = make_user("noshow", "student")
    Enrolment.objects.create(course=course, user=other)
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=100)
    submit_and_grade(assignment, student, lecturer, 60)
    published, skipped = services.publish_results(course, lecturer)
    assert published == 1 and skipped == ["noshow"]


def test_suspended_students_not_published(course, enrolled, student, lecturer, assignment):
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=100)
    submit_and_grade(assignment, student, lecturer, 60)
    Enrolment.objects.filter(user=student).update(status="suspended")
    assert services.publish_results(course, lecturer)[0] == 0


def test_gpa_formula(db, student, course):
    sem = course.semester
    c2 = Course.objects.create(code="CS2", title="Two", semester=sem, credits=2)
    c3 = Course.objects.create(code="CS3", title="Three", semester=Category.objects.create(name="Semester 4", kind="semester"), credits=3)
    now = timezone.now()
    CourseResult.objects.create(course=course, student=student, percent=80, letter="A", points=D("4.00"), credits=4, published_at=now)
    CourseResult.objects.create(course=c2, student=student, percent=60, letter="B", points=D("3.00"), credits=2, published_at=now)
    CourseResult.objects.create(course=c3, student=student, percent=50, letter="C+", points=D("2.30"), credits=3, published_at=now)
    semesters, cumulative, credits = services.results_by_semester(student)
    by = {s["name"]: s for s in semesters}
    assert by["Semester 3"]["gpa"] == D("3.67")  # (4*4 + 3*2) / 6
    assert by["Semester 4"]["gpa"] == D("2.30")
    assert cumulative == D("3.21") and credits == 9  # (16 + 6 + 6.9) / 9
    assert services.gpa([]) is None


# ---------- views ----------

def test_lecturer_sets_up_gradebook(client, course, lecturer, assignment, quiz):
    client.force_login(lecturer)
    url = reverse("grading:item-add", args=[course.pk])
    assert client.post(url, {"kind": "assignment", "assignment": assignment.pk, "weight": "30"}).status_code == 302
    assert client.post(url, {"kind": "quiz", "quiz": quiz.pk, "title": "", "weight": "20"}).status_code == 302
    assert client.post(url, {"kind": "manual", "title": "Final exam", "max_mark": "60", "weight": "50"}).status_code == 302
    assert list(course.grade_items.values_list("title", flat=True)) == ["A1", "Q1", "Final exam"]
    page = client.get(reverse("grading:gradebook", args=[course.pk])).content
    assert b"100%" in page and b"Complete" in page


def test_item_form_validation(client, course, lecturer, assignment):
    client.force_login(lecturer)
    url = reverse("grading:item-add", args=[course.pk])
    for bad in ({"kind": "assignment", "weight": "10"}, {"kind": "manual", "title": "E", "weight": "10"}, {"kind": "manual", "weight": "10", "max_mark": "5"},
                {"kind": "assignment", "assignment": assignment.pk, "weight": "0"}, {"kind": "assignment", "assignment": assignment.pk, "weight": "101"}):
        assert client.post(url, bad).status_code == 200
    assert not course.grade_items.exists()


def test_same_assignment_cannot_be_added_twice(client, course, lecturer, assignment):
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=10)
    client.force_login(lecturer)
    r = client.post(reverse("grading:item-add", args=[course.pk]), {"kind": "assignment", "assignment": assignment.pk, "weight": "10"})
    assert r.status_code == 200 and course.grade_items.count() == 1


def test_manual_marks_entry(client, course, enrolled, student, lecturer):
    item = GradeItem.objects.create(course=course, title="Exam", kind="manual", max_mark=50, weight=100)
    client.force_login(lecturer)
    url = reverse("grading:manual-marks", args=[item.pk])
    r = client.post(url, {f"mark_{student.pk}": "51"}, follow=True)
    assert b"between 0 and 50" in r.content and not ManualMark.objects.exists()
    assert b"not a number" in client.post(url, {f"mark_{student.pk}": "x"}, follow=True).content
    assert client.post(url, {f"mark_{student.pk}": "42.5"}).status_code == 302
    assert ManualMark.objects.get().mark == D("42.50")
    client.post(url, {f"mark_{student.pk}": ""})  # clearing removes it
    assert not ManualMark.objects.exists()


def test_manual_marks_only_for_manual_items(client, course, lecturer, assignment):
    item = GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=10)
    client.force_login(lecturer)
    assert client.get(reverse("grading:manual-marks", args=[item.pk])).status_code == 403


def test_publish_through_view_and_student_sees_results(client, course, enrolled, student, lecturer, assignment):
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=100)
    submit_and_grade(assignment, student, lecturer, 90)
    client.force_login(student)
    assert b"No results yet" in client.get(reverse("grading:my-results")).content
    assert b"90" in client.get(reverse("grading:my-grades")).content
    client.force_login(lecturer)
    assert client.post(reverse("grading:publish", args=[course.pk])).status_code == 302
    client.force_login(student)
    body = client.get(reverse("grading:my-results")).content
    assert b"4.00" in body and b"A+" in body and b"Semester 3" in body


def test_permissions(client, course, enrolled, student, make_user, assignment):
    item = GradeItem.objects.create(course=course, title="Exam", kind="manual", max_mark=10, weight=10)
    for u in (student, make_user("intruder", "lecturer")):
        client.force_login(u)
        assert client.get(reverse("grading:gradebook", args=[course.pk])).status_code == 403
        assert client.get(reverse("grading:export", args=[course.pk])).status_code == 403
        assert client.post(reverse("grading:publish", args=[course.pk])).status_code == 403
        assert client.post(reverse("grading:item-delete", args=[item.pk])).status_code == 403
        assert client.get(reverse("grading:manual-marks", args=[item.pk])).status_code == 403
    client.force_login(student)
    assert client.get(reverse("grading:gradebook-list")).status_code == 403
    client.force_login(make_user("lect2", "lecturer"))
    assert client.get(reverse("grading:my-grades")).status_code == 403


def test_csv_export_and_formula_injection(client, course, enrolled, student, lecturer, assignment):
    student.first_name, student.last_name = "=HYPERLINK(\"http://evil\")", "X"
    student.save()
    GradeItem.objects.create(course=course, title="=BAD", kind="assignment", assignment=assignment, weight=100)
    submit_and_grade(assignment, student, lecturer, 55)
    client.force_login(lecturer)
    r = client.get(reverse("grading:export", args=[course.pk]))
    text = r.content.decode()
    assert r["Content-Type"].startswith("text/csv") and "attachment" in r["Content-Disposition"]
    assert "'=BAD" in text and "'=HYPERLINK" in text
    assert "\n=" not in text and ",=" not in text
    assert "55" in text


def test_admin_can_open_any_gradebook(client, course, admin_user):
    client.force_login(admin_user)
    assert client.get(reverse("grading:gradebook", args=[course.pk])).status_code == 200


def test_weight_edit_and_delete(client, course, lecturer, assignment):
    item = GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=assignment, weight=10)
    client.force_login(lecturer)
    client.post(reverse("grading:item-edit", args=[item.pk]), {"title": "Essay", "weight": "25"})
    item.refresh_from_db()
    assert item.title == "Essay" and item.weight == D("25")
    client.post(reverse("grading:item-delete", args=[item.pk]))
    assert not GradeItem.objects.exists() and Assignment.objects.filter(pk=assignment.pk).exists()
