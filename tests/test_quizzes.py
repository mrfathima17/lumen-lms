from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AllowedNetwork, SiteSettings
from apps.quizzes import services
from apps.quizzes.models import Answer, Attempt, Choice, Question, Quiz


@pytest.fixture
def quiz(course):
    qz = Quiz.objects.create(course=course, title="Quiz 1", time_limit_minutes=30, max_attempts=2)
    mcq = Question.objects.create(quiz=qz, kind="mcq", text="2+2?", marks=2, position=0)
    Choice.objects.create(question=mcq, text="3", position=0)
    Choice.objects.create(question=mcq, text="4", is_correct=True, position=1)
    tf = Question.objects.create(quiz=qz, kind="tf", text="Sky is blue", marks=1, position=1)
    Choice.objects.create(question=tf, text="True", is_correct=True, position=0)
    Choice.objects.create(question=tf, text="False", position=1)
    Question.objects.create(quiz=qz, kind="short", text="Capital of France?", marks=2, position=2, accepted_answers="Paris\nparis, france")
    Question.objects.create(quiz=qz, kind="essay", text="Explain normalisation", marks=5, position=3)
    return qz


def q_of(quiz, kind):
    return quiz.questions.get(kind=kind)


def correct(q):
    return q.choices.get(is_correct=True).pk


def wrong(q):
    return q.choices.get(is_correct=False).pk


# ---------- rules ----------

def test_availability(quiz):
    now = timezone.now()
    assert services.availability(quiz, now)[0]
    quiz.opens_at = now + timedelta(hours=1)
    assert "not opened" in services.availability(quiz, now)[1]
    quiz.opens_at, quiz.closes_at = None, now - timedelta(minutes=1)
    assert "closed" in services.availability(quiz, now)[1]
    quiz.closes_at, quiz.is_enabled = None, False
    assert "paused" in services.availability(quiz, now)[1]
    quiz.is_enabled, quiz.is_visible = True, False
    assert not services.availability(quiz, now)[0]


def test_empty_quiz_not_available(course):
    assert not services.availability(Quiz.objects.create(course=course, title="Empty"))[0]


def test_deadline_is_earlier_of_limit_and_close(quiz):
    t0 = timezone.now()
    assert services.compute_deadline(quiz, t0) == t0 + timedelta(minutes=30)
    quiz.closes_at = t0 + timedelta(minutes=10)
    assert services.compute_deadline(quiz, t0) == t0 + timedelta(minutes=10)
    quiz.time_limit_minutes, quiz.closes_at = None, None
    assert services.compute_deadline(quiz, t0) is None


def test_start_resume_and_attempt_limit(quiz, enrolled, student):
    a1 = services.start_attempt(quiz, student)
    assert services.start_attempt(quiz, student).pk == a1.pk  # resume, no second attempt
    services.finish_attempt(a1)
    a2 = services.start_attempt(quiz, student)
    assert a2.number == 2
    services.finish_attempt(a2)
    with pytest.raises(services.QuizError, match="all your attempts"):
        services.start_attempt(quiz, student)


def test_start_requires_enrolment(quiz, make_user):
    with pytest.raises(services.QuizError):
        services.start_attempt(quiz, make_user("out", "student"))


def test_cannot_start_when_closed(quiz, enrolled, student):
    quiz.closes_at = timezone.now() - timedelta(minutes=1); quiz.save()
    with pytest.raises(services.QuizError, match="closed"):
        services.start_attempt(quiz, student)


def test_autosave_rules(quiz, enrolled, student):
    a = services.start_attempt(quiz, student)
    mcq = q_of(quiz, "mcq")
    services.save_answer(a, mcq, choice_id=wrong(mcq))
    services.save_answer(a, mcq, choice_id=correct(mcq))  # overwrite, still one row
    assert Answer.objects.filter(attempt=a, question=mcq).count() == 1
    other = q_of(quiz, "tf")
    with pytest.raises(services.QuizError):
        services.save_answer(a, mcq, choice_id=correct(other))  # choice from another question
    services.save_answer(a, mcq, choice_id="")  # clearing removes the answer
    assert not Answer.objects.filter(attempt=a, question=mcq).exists()
    with pytest.raises(services.QuizError, match="Time is up"):
        services.save_answer(a, mcq, choice_id=correct(mcq), now=a.deadline_at + timedelta(seconds=1))


def test_answer_for_other_quiz_refused(quiz, course, enrolled, student):
    other = Quiz.objects.create(course=course, title="Other")
    foreign = Question.objects.create(quiz=other, kind="essay", text="x")
    a = services.start_attempt(quiz, student)
    with pytest.raises(services.QuizError):
        services.save_answer(a, foreign, text="hi")


def full_attempt(quiz, student, mcq_ok=True, tf_ok=True, short="Paris", essay="Because."):
    a = services.start_attempt(quiz, student)
    mcq, tf = q_of(quiz, "mcq"), q_of(quiz, "tf")
    services.save_answer(a, mcq, choice_id=correct(mcq) if mcq_ok else wrong(mcq))
    services.save_answer(a, tf, choice_id=correct(tf) if tf_ok else wrong(tf))
    services.save_answer(a, q_of(quiz, "short"), text=short)
    if essay is not None:
        services.save_answer(a, q_of(quiz, "essay"), text=essay)
    return a


def test_auto_marking_and_pending_essay(quiz, enrolled, student):
    a = services.finish_attempt(full_attempt(quiz, student))
    assert a.score == Decimal("5.00") and a.status == Attempt.Status.SUBMITTED  # essay still waiting


def test_all_wrong_scores_zero(quiz, enrolled, student):
    a = services.finish_attempt(full_attempt(quiz, student, False, False, "Lyon", essay=None))
    assert a.score == 0 and a.status == Attempt.Status.GRADED


def test_short_answer_matching_ignores_case_and_spaces(quiz, enrolled, student):
    a = services.finish_attempt(full_attempt(quiz, student, False, False, "  PARIS  ", essay=None))
    assert a.score == Decimal("2.00")
    b = services.start_attempt(quiz, student)
    services.save_answer(b, q_of(quiz, "short"), text="paris, france")
    assert services.finish_attempt(b).score == Decimal("2.00")


def test_short_without_accepted_answers_is_manual(quiz, enrolled, student):
    sq = q_of(quiz, "short"); sq.accepted_answers = ""; sq.save()
    a = services.finish_attempt(full_attempt(quiz, student, essay=None))
    assert a.status == Attempt.Status.SUBMITTED


def test_manual_grading_completes_attempt(quiz, enrolled, student):
    a = services.finish_attempt(full_attempt(quiz, student))
    essay_ans = a.answers.get(question__kind="essay")
    with pytest.raises(ValueError):
        services.manual_grade(a, {essay_ans.pk: Decimal("6")})
    a.refresh_from_db()
    assert a.status == Attempt.Status.SUBMITTED
    services.manual_grade(a, {essay_ans.pk: Decimal("4")}, {essay_ans.pk: "Good"})
    a.refresh_from_db()
    assert a.score == Decimal("9.00") and a.status == Attempt.Status.GRADED


def test_late_finish_is_recorded_at_deadline(quiz, enrolled, student):
    a = full_attempt(quiz, student, essay=None)
    services.finish_attempt(a, now=a.deadline_at + timedelta(minutes=10))
    assert a.submitted_at == a.deadline_at


def test_finish_twice_is_harmless(quiz, enrolled, student):
    a = services.finish_attempt(full_attempt(quiz, student, essay=None))
    s = a.score
    assert services.finish_attempt(a).score == s


def test_expire_overdue_submits_stale_attempts(quiz, enrolled, student, make_user):
    a = full_attempt(quiz, student, essay=None)
    Attempt.objects.filter(pk=a.pk).update(deadline_at=timezone.now() - timedelta(seconds=5))
    assert services.expire_overdue() == 1
    a.refresh_from_db()
    assert a.status != Attempt.Status.IN_PROGRESS and a.score == Decimal("5.00")


def test_review_policy(quiz, enrolled, student):
    a = services.finish_attempt(full_attempt(quiz, student, essay=None))
    now = timezone.now()
    quiz.closes_at = now + timedelta(days=1)
    assert quiz.effective_review_policy == "after_close"  # system default
    assert not services.review_allowed(quiz, a, now)
    assert services.review_allowed(quiz, a, now + timedelta(days=2))
    quiz.closes_at = None
    assert services.review_allowed(quiz, a, now)  # nothing to wait for
    quiz.review_policy = "manual"
    assert not services.review_allowed(quiz, a, now)
    quiz.review_released = True
    assert services.review_allowed(quiz, a, now)
    quiz.review_policy = "immediate"; quiz.review_released = False; quiz.closes_at = now + timedelta(days=1)
    assert services.review_allowed(quiz, a, now)


def test_review_never_while_in_progress(quiz, enrolled, student):
    a = services.start_attempt(quiz, student)
    quiz.review_policy = "immediate"
    assert not services.review_allowed(quiz, a)


def test_site_default_review_policy_is_used(quiz, enrolled, student):
    s = SiteSettings.load(); s.quiz_review_policy = "immediate"; s.save()
    assert quiz.effective_review_policy == "immediate"


# ---------- views ----------

def test_student_flow_through_views(client, quiz, enrolled, student):
    client.force_login(student)
    assert b"Start attempt" in client.get(reverse("quizzes:student-detail", args=[quiz.pk])).content
    r = client.post(reverse("quizzes:start", args=[quiz.pk]))
    a = Attempt.objects.get(student=student)
    assert r.url == reverse("quizzes:attempt", args=[a.pk])
    page = client.get(r.url).content
    assert b"2+2?" in page and b"Time left" in page and b"hx-post" in page
    mcq = q_of(quiz, "mcq")
    save = reverse("quizzes:save-answer", args=[a.pk, mcq.pk])
    assert b"Saved" in client.post(save, {"choice": correct(mcq)}).content
    assert b'checked' in client.get(r.url).content  # saved answer is restored on reload
    assert client.post(reverse("quizzes:finish", args=[a.pk])).status_code == 302
    res = client.get(reverse("quizzes:result", args=[a.pk]))
    assert res.status_code == 200 and b">2/10<" in res.content  # 2 marks of 10: only the first question was answered
    a.refresh_from_db()
    assert a.status == Attempt.Status.GRADED and a.score == Decimal("2.00")
    assert b"Capital of France?" in res.content  # no closing date, so nothing to wait for: review is open


def test_autosave_after_deadline_returns_409(client, quiz, enrolled, student):
    client.force_login(student)
    a = services.start_attempt(quiz, student)
    Attempt.objects.filter(pk=a.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
    mcq = q_of(quiz, "mcq")
    # the view auto-submits an expired attempt first, so a late autosave is refused
    assert client.post(reverse("quizzes:save-answer", args=[a.pk, mcq.pk]), {"choice": correct(mcq)}).status_code == 409
    a.refresh_from_db()
    assert a.status != Attempt.Status.IN_PROGRESS


def test_opening_expired_attempt_submits_it(client, quiz, enrolled, student):
    client.force_login(student)
    a = full_attempt(quiz, student, essay=None)
    Attempt.objects.filter(pk=a.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
    r = client.get(reverse("quizzes:attempt", args=[a.pk]))
    assert r.status_code == 302 and r.url == reverse("quizzes:result", args=[a.pk])


def test_other_student_cannot_touch_attempt(client, quiz, enrolled, student, make_user):
    a = services.start_attempt(quiz, student)
    mcq = q_of(quiz, "mcq")
    client.force_login(make_user("rival", "student"))
    for url, method in ((reverse("quizzes:attempt", args=[a.pk]), "get"), (reverse("quizzes:result", args=[a.pk]), "get"),
                        (reverse("quizzes:save-answer", args=[a.pk, mcq.pk]), "post"), (reverse("quizzes:finish", args=[a.pk]), "post")):
        assert getattr(client, method)(url).status_code == 403


def test_hidden_or_unenrolled_quiz_blocked(client, quiz, enrolled, student, make_user):
    client.force_login(make_user("out", "student"))
    assert client.get(reverse("quizzes:student-detail", args=[quiz.pk])).status_code == 403
    client.force_login(student)
    quiz.is_visible = False; quiz.save()
    assert client.get(reverse("quizzes:student-detail", args=[quiz.pk])).status_code == 403
    assert client.post(reverse("quizzes:start", args=[quiz.pk])).status_code == 403


def test_review_shown_after_policy_allows(client, quiz, enrolled, student):
    quiz.review_policy = "immediate"; quiz.save()
    a = services.finish_attempt(full_attempt(quiz, student, essay=None))
    client.force_login(student)
    body = client.get(reverse("quizzes:result", args=[a.pk])).content
    assert b"Capital of France?" in body and b"Your answer" in body


def test_network_rule_blocks_taking_but_not_editing(client, quiz, enrolled, student, lecturer):
    AllowedNetwork.objects.create(name="Campus", cidr="10.20.0.0/16", scope="quiz")
    client.force_login(student)
    assert client.get(reverse("quizzes:student-detail", args=[quiz.pk]), REMOTE_ADDR="8.8.8.8").status_code == 403
    assert client.post(reverse("quizzes:start", args=[quiz.pk]), REMOTE_ADDR="8.8.8.8").status_code == 403
    assert client.get(reverse("quizzes:student-detail", args=[quiz.pk]), REMOTE_ADDR="10.20.1.1").status_code == 200
    client.force_login(lecturer)
    assert client.get(reverse("quizzes:editor", args=[quiz.pk]), REMOTE_ADDR="8.8.8.8").status_code == 200


def test_network_rule_blocks_autosave_mid_attempt(client, quiz, enrolled, student):
    a = services.start_attempt(quiz, student)
    mcq = q_of(quiz, "mcq")
    AllowedNetwork.objects.create(name="Campus", cidr="10.20.0.0/16", scope="quiz")
    client.force_login(student)
    r = client.post(reverse("quizzes:save-answer", args=[a.pk, mcq.pk]), {"choice": correct(mcq)}, REMOTE_ADDR="8.8.8.8")
    assert r.status_code == 403 and not Answer.objects.exists()


# ---------- lecturer side ----------

def test_lecturer_builds_quiz_and_questions(client, course, lecturer):
    client.force_login(lecturer)
    r = client.post(reverse("quizzes:new", args=[course.pk]), {"title": "Midterm", "time_limit_minutes": 20, "max_attempts": 1, "is_visible": "on", "is_enabled": "on"})
    quiz = Quiz.objects.get(title="Midterm")
    assert r.url == reverse("quizzes:editor", args=[quiz.pk])
    url = reverse("quizzes:question-new", args=[quiz.pk])
    r = client.post(url, {"kind": "mcq", "text": "Pick", "marks": "2", "choice_1": "A", "choice_2": "B", "choice_3": "", "choice_4": "", "correct": "2"})
    assert r.status_code == 302
    q = quiz.questions.get()
    assert [(c.text, c.is_correct) for c in q.choices.all()] == [("A", False), ("B", True)]
    r = client.post(url, {"kind": "tf", "text": "True?", "marks": "1", "tf_correct": "false"})
    assert quiz.questions.get(kind="tf").choices.get(is_correct=True).text == "False"
    client.post(url, {"kind": "essay", "text": "Discuss", "marks": "5"})
    assert quiz.total_marks == Decimal("8")


def test_question_validation(client, course, lecturer, quiz):
    client.force_login(lecturer)
    url = reverse("quizzes:question-new", args=[quiz.pk])
    n = quiz.questions.count()
    bad = [
        {"kind": "mcq", "text": "x", "marks": "1", "choice_1": "only", "correct": "1"},
        {"kind": "mcq", "text": "x", "marks": "1", "choice_1": "a", "choice_2": "b"},
        {"kind": "mcq", "text": "x", "marks": "1", "choice_1": "a", "choice_2": "b", "correct": "4"},
        {"kind": "tf", "text": "x", "marks": "1"},
        {"kind": "essay", "text": "x", "marks": "0"},
    ]
    for data in bad:
        assert client.post(url, data).status_code == 200
    assert quiz.questions.count() == n


def test_quiz_settings_validation(client, course, lecturer):
    client.force_login(lecturer)
    url = reverse("quizzes:new", args=[course.pk])
    t = timezone.localtime()
    o, c = (t + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"), (t + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(url, {"title": "Bad", "max_attempts": 1, "opens_at": o, "closes_at": c, "is_visible": "on", "is_enabled": "on"})
    assert r.status_code == 200 and not Quiz.objects.filter(title="Bad").exists()
    r = client.post(url, {"title": "Bad2", "max_attempts": 99, "is_visible": "on", "is_enabled": "on"})
    assert r.status_code == 200


def test_questions_locked_once_attempts_exist(client, quiz, enrolled, student, lecturer):
    services.start_attempt(quiz, student)
    client.force_login(lecturer)
    q = q_of(quiz, "essay")
    assert client.get(reverse("quizzes:question-edit", args=[q.pk])).status_code == 302
    client.post(reverse("quizzes:question-delete", args=[q.pk]))
    assert Question.objects.filter(pk=q.pk).exists()
    assert client.get(reverse("quizzes:question-new", args=[quiz.pk])).status_code == 302


def test_lecturer_marks_essay_through_view(client, quiz, enrolled, student, lecturer):
    a = services.finish_attempt(full_attempt(quiz, student))
    ans = a.answers.get(question__kind="essay")
    client.force_login(lecturer)
    url = reverse("quizzes:grade", args=[a.pk])
    assert b"between 0 and 5" in client.post(url, {f"mark_{ans.pk}": "9"}, follow=True).content
    assert b"not a number" in client.post(url, {f"mark_{ans.pk}": "abc"}, follow=True).content
    r = client.post(url, {f"mark_{ans.pk}": "3.5", f"note_{ans.pk}": "ok"})
    assert r.status_code == 302
    a.refresh_from_db()
    assert a.score == Decimal("8.50") and a.status == "graded"
    client.force_login(student)
    assert b"8.5" in client.get(reverse("quizzes:result", args=[a.pk])).content


def test_in_progress_attempt_cannot_be_graded(client, quiz, enrolled, student, lecturer):
    a = services.start_attempt(quiz, student)
    client.force_login(lecturer)
    assert client.get(reverse("quizzes:grade", args=[a.pk])).status_code == 302


def test_staff_permissions(client, quiz, enrolled, student, make_user):
    for u in (student, make_user("intruder", "lecturer")):
        client.force_login(u)
        assert client.get(reverse("quizzes:editor", args=[quiz.pk])).status_code == 403
        assert client.get(reverse("quizzes:attempts", args=[quiz.pk])).status_code == 403
        assert client.post(reverse("quizzes:action", args=[quiz.pk, "toggle-visible"])).status_code == 403
    client.force_login(student)
    assert client.get(reverse("quizzes:manage-list")).status_code == 403


def test_pause_and_hide_toggles(client, quiz, lecturer):
    client.force_login(lecturer)
    client.post(reverse("quizzes:action", args=[quiz.pk, "toggle-enabled"]))
    quiz.refresh_from_db()
    assert not quiz.is_enabled
    assert client.post(reverse("quizzes:action", args=[quiz.pk, "bogus"])).status_code == 403


def test_close_expired_command(quiz, enrolled, student):
    from django.core.management import call_command
    a = full_attempt(quiz, student, essay=None)
    Attempt.objects.filter(pk=a.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
    call_command("close_expired_attempts")
    a.refresh_from_db()
    assert a.status == Attempt.Status.GRADED


def test_course_page_lists_quizzes_per_role(client, quiz, enrolled, student, lecturer, course):
    client.force_login(student)
    assert b"Quiz 1" in client.get(reverse("courses:detail", args=[course.pk])).content
    quiz.is_visible = False; quiz.save()
    assert b"Quiz 1" not in client.get(reverse("courses:detail", args=[course.pk])).content
    client.force_login(lecturer)
    assert b"Quiz 1" in client.get(reverse("courses:detail", args=[course.pk])).content


def test_attempt_page_restores_every_saved_choice(client, quiz, enrolled, student):
    client.force_login(student)
    a = services.start_attempt(quiz, student)
    mcq, tf = q_of(quiz, "mcq"), q_of(quiz, "tf")
    services.save_answer(a, mcq, choice_id=correct(mcq))
    services.save_answer(a, tf, choice_id=wrong(tf))
    body = client.get(reverse("quizzes:attempt", args=[a.pk])).content.decode()
    assert body.count(" checked") == 2


def test_each_choice_question_is_its_own_form(client, quiz, enrolled, student):
    """Radios share one name; they only stay independent per question when each question has its own <form>."""
    client.force_login(student)
    a = services.start_attempt(quiz, student)
    body = client.get(reverse("quizzes:attempt", args=[a.pk])).content.decode()
    assert body.count('<form hx-post=') == 2  # the multiple-choice and the true/false question
