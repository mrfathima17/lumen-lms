from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.assignments.models import Assignment, Extension, Submission
from apps.core.models import AuditLog
from apps.grading.models import GradeItem
from apps.quizzes.models import Attempt, Choice, Question, Quiz
from apps.surveys.models import Survey, SurveyQuestion


def login(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def asg(course):
    return Assignment.objects.create(course=course, title="ER Diagram", description="Draw it.", due_at=timezone.now() + timedelta(days=2), max_mark=Decimal("100"))


def submit(asg, student, **kw):
    kw.setdefault("submitted_at", timezone.now())
    return Submission.objects.create(assignment=asg, student=student, file="submissions/x.pdf", **kw)


# ---------------- assignments ----------------

def test_student_assignment_page_has_details_card(client, course, enrolled, asg):
    GradeItem.objects.create(course=course, title="ER", kind="assignment", assignment=asg, weight=Decimal("15"))
    html = login(client, enrolled).get(reverse("assignments:detail", args=[asg.pk])).content.decode()
    assert "Instructions" in html and "Your submission" in html and "Details" in html
    assert "Not submitted" in html and "Time left" in html and "15% of the course" in html and "Max mark" in html


def test_graded_assignment_shows_feedback_card(client, course, enrolled, asg, lecturer):
    submit(asg, enrolled, status="graded", raw_mark=Decimal("80"), final_mark=Decimal("80"), feedback="Good work", graded_by=lecturer, graded_at=timezone.now())
    html = login(client, enrolled).get(reverse("assignments:detail", args=[asg.pk])).content.decode()
    assert "Submitted &amp; graded" in html and "80 / 100" in html and "Good work" in html and "Nimal Perera" in html


def test_assignment_lists_have_stats(client, course, enrolled, asg, lecturer):
    html = login(client, enrolled).get(reverse("assignments:overview")).content.decode()
    assert "Due this week" in html and "Awaiting grading" in html
    submit(asg, enrolled)
    html = login(client, lecturer).get(reverse("assignments:overview")).content.decode()
    assert "Need grading" in html and "Missing" in html


def test_submissions_filter_and_stats(client, course, enrolled, asg, lecturer, make_user):
    other = make_user("s2", first_name="Sara")
    from apps.courses.models import Enrolment
    Enrolment.objects.create(course=course, user=other)
    submit(asg, enrolled, status="graded", final_mark=Decimal("70"))
    login(client, lecturer)
    url = reverse("assignments:submissions", args=[asg.pk])
    page = client.get(url).content.decode()
    assert "Need grading" in page and enrolled.username in page or "Amal" in page
    graded_only = client.get(url + "?status=graded").content.decode()
    assert "Amal" in graded_only and "Sara" not in graded_only
    assert "Nothing matches" in client.get(url + "?status=late").content.decode()


def test_grade_page_has_prev_next_and_save_next(client, course, enrolled, asg, lecturer, make_user):
    from apps.courses.models import Enrolment
    second = make_user("s2", first_name="Zed")
    Enrolment.objects.create(course=course, user=second)
    first = submit(asg, enrolled)
    nxt = submit(asg, second)
    login(client, lecturer)
    page = client.get(reverse("assignments:grade", args=[first.pk])).content.decode()
    assert "Next" in page and "Save &amp; next" in page
    res = client.post(reverse("assignments:grade", args=[first.pk]), {"raw_mark": "60", "feedback": "ok", "save_next": "1"})
    assert res.status_code == 302 and res.url == reverse("assignments:grade", args=[nxt.pk])
    res = client.post(reverse("assignments:grade", args=[nxt.pk]), {"raw_mark": "50", "feedback": "", "save_next": "1"})
    assert res.url == reverse("assignments:submissions", args=[asg.pk])  # last one: back to the list


def test_extension_can_be_removed(client, course, enrolled, asg, lecturer):
    ext = Extension.objects.create(assignment=asg, student=enrolled, due_at=asg.due_at + timedelta(days=2), granted_by=lecturer)
    login(client, lecturer)
    assert "Active extensions" in client.get(reverse("assignments:extensions", args=[asg.pk])).content.decode()
    url = reverse("assignments:extension-delete", args=[asg.pk, ext.pk])
    assert client.get(url).status_code == 405
    assert client.post(url).status_code == 302
    assert not Extension.objects.exists()
    assert AuditLog.objects.filter(action="extension_removed").exists()


def test_student_cannot_remove_extension(client, course, enrolled, asg, lecturer):
    ext = Extension.objects.create(assignment=asg, student=enrolled, due_at=asg.due_at + timedelta(days=2), granted_by=lecturer)
    assert login(client, enrolled).post(reverse("assignments:extension-delete", args=[asg.pk, ext.pk])).status_code == 403
    assert Extension.objects.exists()


def test_assignment_form_has_options_toggles(client, course, lecturer):
    html = login(client, lecturer).get(reverse("assignments:new", args=[course.pk])).content.decode()
    assert "Create assignment" in html and "Allow late submissions" in html and 'class="toggle"' in html
    res = client.post(reverse("assignments:new", args=[course.pk]), {"title": "T", "due_at": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"), "max_mark": "50", "is_visible": "on"})
    assert res.status_code == 302
    a = Assignment.objects.get(title="T")
    assert a.is_visible and not a.allow_late  # unticked toggle really means off


# ---------------- quizzes ----------------

@pytest.fixture
def quiz(course):
    qz = Quiz.objects.create(course=course, title="Quiz 3", time_limit_minutes=20, max_attempts=2)
    q = Question.objects.create(quiz=qz, kind="mcq", text="2+2?", marks=2, position=0)
    Choice.objects.create(question=q, text="3", position=0)
    Choice.objects.create(question=q, text="4", is_correct=True, position=1)
    return qz


def test_quiz_start_page(client, course, enrolled, quiz):
    other = Quiz.objects.create(course=course, title="Quiz 2")
    q = Question.objects.create(quiz=other, kind="short", text="x", marks=10, position=0)
    Attempt.objects.create(quiz=other, student=enrolled, number=1, started_at=timezone.now(), submitted_at=timezone.now(), status="graded", score=Decimal("7"))
    html = login(client, enrolled).get(reverse("quizzes:student-detail", args=[quiz.pk])).content.decode()
    assert "Before you begin" in html and "20 minutes" in html and "Summary" in html and "0 of 2 used" in html
    assert "Previous quizzes" in html and "Quiz 2" in html and "7 / 10" in html


def test_attempt_page_has_navigation(client, course, enrolled, quiz):
    from apps.quizzes import services
    a = services.start_attempt(quiz, enrolled)
    html = login(client, enrolled).get(reverse("quizzes:attempt", args=[a.pk])).content.decode()
    assert "Navigation" in html and 'class="qnav"' in html and "Question 1 of 1" in html and "Time left" in html


def test_result_page_ring_and_time_taken(client, course, enrolled, quiz):
    now = timezone.now()
    a = Attempt.objects.create(quiz=quiz, student=enrolled, number=1, started_at=now - timedelta(minutes=14, seconds=32), submitted_at=now, status="graded", score=Decimal("2"))
    html = login(client, enrolled).get(reverse("quizzes:result", args=[a.pk])).content.decode()
    assert "100%" in html and "Well done" in html and "time taken 14:32" in html and "Back to course" in html


def test_attempts_page_stats(client, course, enrolled, quiz, lecturer):
    Attempt.objects.create(quiz=quiz, student=enrolled, number=1, started_at=timezone.now(), submitted_at=timezone.now(), status="graded", score=Decimal("1"))
    html = login(client, lecturer).get(reverse("quizzes:attempts", args=[quiz.pk])).content.decode()
    assert "1 / 1" in html and "50%" in html and "Highest" in html and "Finished" in html


def test_quiz_editor_has_status_card(client, course, quiz, lecturer):
    html = login(client, lecturer).get(reverse("quizzes:editor", args=[quiz.pk])).content.decode()
    assert 'class="qb"' in html and "Quiz status" in html and "Pause quiz" in html


# ---------------- surveys ----------------

@pytest.fixture
def poll(course):
    s = Survey.objects.create(course=course, kind="poll", title="Lab time", is_visible=True, show_results="after_vote")
    SurveyQuestion.objects.create(survey=s, text="When?", kind="single", choices="Mon\nTue")
    SurveyQuestion.objects.create(survey=s, text="Rate it", kind="rating", required=False)
    return s


def test_poll_page_looks_like_prototype(client, course, enrolled, poll):
    html = login(client, enrolled).get(reverse("surveys:student-detail", args=[poll.pk])).content.decode()
    assert 'class="po"' in html and 'class="sc"' in html and "Submit my vote" in html and "Poll details" in html and "Shown after you answer" in html


def test_staff_results_have_stats(client, course, enrolled, poll, lecturer):
    q = poll.questions.get(kind="single")
    client.force_login(enrolled)
    client.post(reverse("surveys:student-detail", args=[poll.pk]), {f"q{q.pk}": "Mon", f"q{poll.questions.get(kind='rating').pk}": "4"})
    html = login(client, lecturer).get(reverse("surveys:results", args=[poll.pk])).content.decode()
    assert "Responses" in html and "1 / 1" in html and "4.0 / 5" in html and "Written comments" in html and 'class="res"' in html


def test_grade_page_survives_a_missing_file(client, course, enrolled, asg, lecturer):
    sub = submit(asg, enrolled)  # the file row points at nothing on disk
    html = login(client, lecturer).get(reverse("assignments:grade", args=[sub.pk])).content.decode()
    assert "File not found on the server" in html


def test_quiz_manual_grading_regrade_reset(client, lecturer, course, enrolled, student):
    from decimal import Decimal
    from django.utils import timezone
    from apps.quizzes import services as qs
    from apps.quizzes.models import Answer, Attempt, Choice, Question, Quiz
    quiz = Quiz.objects.create(course=course, title="Q", is_visible=True, is_enabled=True) if hasattr(Quiz, "is_enabled") else Quiz.objects.create(course=course, title="Q")
    mcq = Question.objects.create(quiz=quiz, kind="mcq", text="pick", marks=2, position=0)
    right = Choice.objects.create(question=mcq, text="a", is_correct=True)
    essay = Question.objects.create(quiz=quiz, kind="essay", text="explain", marks=4, position=1)
    att = Attempt.objects.create(quiz=quiz, student=student, number=1, started_at=timezone.now())
    Answer.objects.create(attempt=att, question=mcq, choice=right)
    ea = Answer.objects.create(attempt=att, question=essay, text="because")
    qs.finish_attempt(att)
    att.refresh_from_db()
    assert att.status == "submitted"
    client.force_login(lecturer)
    html = client.get(reverse("quizzes:attempts", args=[quiz.pk])).content.decode()
    assert "Manual grading (1)" in html and "Regrade" in html and "Reset" in html
    page = client.get(reverse("quizzes:marking", args=[quiz.pk])).content.decode()
    assert "explain" in page and "because" in page
    assert client.post(reverse("quizzes:marking", args=[quiz.pk]) + f"?q={essay.pk}", {f"mark_{ea.pk}": "9"}).status_code == 200  # over the maximum
    r = client.post(reverse("quizzes:marking", args=[quiz.pk]) + f"?q={essay.pk}", {f"mark_{ea.pk}": "3"})
    assert r.status_code == 302
    att.refresh_from_db()
    assert att.status == "graded" and att.score == Decimal("5")
    right.is_correct = False
    right.save()
    assert client.post(reverse("quizzes:regrade", args=[att.pk])).status_code == 302
    att.refresh_from_db()
    assert att.score == Decimal("3")
    client.force_login(student)
    assert client.post(reverse("quizzes:reset", args=[att.pk])).status_code == 403
    client.force_login(lecturer)
    client.post(reverse("quizzes:reset", args=[att.pk]))
    assert not Attempt.objects.filter(pk=att.pk).exists()


def test_poll_created_with_question_and_options(client, lecturer, course):
    from apps.surveys.models import Survey
    client.force_login(lecturer)
    url = reverse("surveys:new", args=[course.pk])
    bad = client.post(url, {"kind": "poll", "title": "P", "poll_question": "When?", "poll_options": "Only one", "show_results": "never"})
    assert bad.status_code == 200 and b"at least two options" in bad.content
    ok = client.post(url, {"kind": "poll", "title": "P", "poll_question": "When?", "poll_options": "Tue\nThu\nTue", "show_results": "never"})
    assert ok.status_code == 302
    q = Survey.objects.get(title="P").questions.get()
    assert q.text == "When?" and q.choice_list == ["Tue", "Thu"]


def test_staff_participants_show_last_active_and_risk(client, lecturer, course, enrolled, student):
    client.force_login(lecturer)
    html = client.get(reverse("courses:participants", args=[course.pk])).content.decode()
    assert "Last active" in html and "Search by name or ID" in html and "At risk" in html and "Never" in html


def test_site_password_policy_is_enforced(db, settings):
    settings.AUTH_PASSWORD_VALIDATORS = [{"NAME": "apps.core.validators.SitePasswordPolicyValidator"}]
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from apps.core.models import SiteSettings
    cfg = SiteSettings.load()
    cfg.password_min_length, cfg.password_require_upper, cfg.password_require_number, cfg.password_require_symbol = 12, True, True, True
    cfg.save()
    for weak in ("shortA1!", "alllowercase-xyz-123!", "NoNumbersHere!!!!", "NoSymbolsHere1234"):
        with pytest.raises(ValidationError):
            validate_password(weak)
    validate_password("Lumen-Strong-Pass-42!")


def test_admin_saves_password_policy_and_support_email(client, admin_user):
    from apps.core.models import SiteSettings
    client.force_login(admin_user)
    base = {"site_name": "Lumen", "late_penalty_percent_per_day": 10, "quiz_review_policy": "after_close", "attendance_warning_percent": 80,
            "private_files_quota_mb": 500, "audit_log_retention_months": 12, "two_factor_policy": "off", "maintenance_message": "x"}
    r = client.post(reverse("administration:settings"), {**base, "password_min_length": 4, "support_email": "help@lumen.edu"})
    assert r.status_code == 200  # minimum length below 8 refused
    r = client.post(reverse("administration:settings"), {**base, "password_min_length": 12, "password_require_upper": "on", "support_email": "help@lumen.edu"})
    assert r.status_code == 302
    cfg = SiteSettings.load()
    assert cfg.password_min_length == 12 and cfg.password_require_upper and not cfg.password_require_symbol and cfg.support_email == "help@lumen.edu"
    assert b"help@lumen.edu" in client.get(reverse("core:help")).content


def test_audit_log_csv_export_and_blocked_attempts(client, admin_user):
    from apps.core import audit as audit_mod
    from apps.core.models import AuditLog
    AuditLog.objects.create(action="ip_blocked", target="/quizzes/1/", ip_address="9.9.9.9", result="blocked")
    AuditLog.objects.create(action="login_failed", target="=cmd|x", ip_address="8.8.8.8", result="failed")
    client.force_login(admin_user)
    r = client.get(reverse("administration:audit-export") + "?category=blocked")
    body = r.content.decode()
    assert r["Content-Type"].startswith("text/csv") and "9.9.9.9" in body and "8.8.8.8" not in body
    full = client.get(reverse("administration:audit-export")).content.decode()
    assert "'=cmd" in full or "=cmd|x" not in full.replace("'=cmd", "")
    assert "9.9.9.9" in client.get(reverse("administration:access")).content.decode()
    assert b"Export CSV" in client.get(reverse("administration:audit")).content
