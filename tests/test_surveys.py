from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import ModuleSetting
from apps.messaging.models import Notification
from apps.surveys import services
from apps.surveys.models import Answer, Submission, Survey, SurveyQuestion


def as_user(u):
    c = Client()
    c.force_login(u)
    return c


@pytest.fixture
def survey(course):
    s = Survey.objects.create(course=course, title="Feedback", is_visible=True, published_at=timezone.now())
    SurveyQuestion.objects.create(survey=s, position=1, text="Pace?", kind="single", choices="Too slow\nJust right\nToo fast")
    SurveyQuestion.objects.create(survey=s, position=2, text="Topics", kind="multiple", choices="SQL\nERD\nNormal forms", required=False)
    SurveyQuestion.objects.create(survey=s, position=3, text="Rate it", kind="rating")
    SurveyQuestion.objects.create(survey=s, position=4, text="Comments", kind="text", required=False)
    return s


def answers(s, **over):
    q = list(s.questions.all())
    data = {f"q{q[0].pk}": "Just right", f"q{q[1].pk}": ["SQL", "ERD"], f"q{q[2].pk}": "4", f"q{q[3].pk}": "Good course"}
    data.update(over)
    return data


def test_student_answers_once(enrolled, survey):
    c = as_user(enrolled)
    r = c.post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey))
    assert r.status_code == 302 and survey.submissions.count() == 1 and Answer.objects.count() == 5
    c.post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey))
    assert survey.submissions.count() == 1 and Answer.objects.count() == 5


def test_required_question_blocks_and_keeps_input(enrolled, survey):
    q = list(survey.questions.all())
    r = as_user(enrolled).post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey, **{f"q{q[2].pk}": ""}))
    assert r.status_code == 200 and b"Please answer this question." in r.content and b"Good course" in r.content
    assert survey.submissions.count() == 0


def test_invalid_choice_is_ignored(enrolled, survey):
    q = list(survey.questions.all())
    r = as_user(enrolled).post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey, **{f"q{q[0].pk}": "Made up"}))
    assert r.status_code == 200 and survey.submissions.count() == 0


def test_closed_and_not_open_refuse_answers(enrolled, survey):
    survey.closes_at = timezone.now() - timedelta(minutes=1)
    survey.save()
    as_user(enrolled).post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey))
    assert survey.submissions.count() == 0
    survey.closes_at, survey.opens_at = None, timezone.now() + timedelta(days=1)
    survey.save()
    as_user(enrolled).post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey))
    assert survey.submissions.count() == 0


def test_draft_and_other_courses_are_hidden(enrolled, survey, make_user):
    survey.is_visible = False
    survey.save()
    assert as_user(enrolled).get(reverse("surveys:student-detail", args=[survey.pk])).status_code == 404
    survey.is_visible = True
    survey.save()
    assert as_user(make_user("other", "student")).get(reverse("surveys:student-detail", args=[survey.pk])).status_code == 404


def test_anonymous_answers_have_no_link(enrolled, survey):
    survey.anonymous = True
    survey.save()
    as_user(enrolled).post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey))
    assert Submission.objects.count() == 1 and not Answer.objects.exclude(submission=None).exists()
    took, missing = services.participants(survey)
    assert took == [enrolled]


def test_results_and_visibility_for_students(enrolled, survey):
    c = as_user(enrolled)
    url = reverse("surveys:student-detail", args=[survey.pk])
    c.post(url, answers(survey))
    assert b"Results (" not in c.get(url).content  # never
    survey.show_results = "after_vote"
    survey.save()
    page = c.get(url).content
    assert b"Results (1 answer)" in page and b"Good course" not in page.split(b"Results (")[1]  # written answers stay private
    r = services.results(survey)
    assert r["total"] == 1 and r["rows"][2]["average"] == 4 and r["rows"][0]["bars"][1]["count"] == 1


def test_after_close_results(enrolled, survey):
    survey.show_results = "after_close"
    survey.save()
    c = as_user(enrolled)
    url = reverse("surveys:student-detail", args=[survey.pk])
    c.post(url, answers(survey))
    assert b"Results (" not in c.get(url).content
    survey.closes_at = timezone.now() - timedelta(minutes=1)
    survey.save()
    assert b"Results (" in c.get(url).content


def test_students_cannot_use_the_manager(enrolled, survey):
    c = as_user(enrolled)
    for name, args in [("surveys:manage-list", []), ("surveys:editor", [survey.pk]), ("surveys:results", [survey.pk]), ("surveys:export", [survey.pk])]:
        assert c.get(reverse(name, args=args)).status_code == 403
    assert c.post(reverse("surveys:delete", args=[survey.pk])).status_code == 403


def test_other_lecturer_cannot_manage(survey, make_user):
    other = make_user("lect2", "lecturer")
    c = as_user(other)
    assert c.get(reverse("surveys:results", args=[survey.pk])).status_code == 403
    assert c.post(reverse("surveys:delete", args=[survey.pk])).status_code == 403
    assert Survey.objects.filter(pk=survey.pk).exists()


def test_lecturer_creates_and_publishing_notifies(lecturer, enrolled, course, django_capture_on_commit_callbacks):
    c = as_user(lecturer)
    with django_capture_on_commit_callbacks(execute=True):
        r = c.post(reverse("surveys:new", args=[course.pk]), {"kind": "poll", "title": "Pick a day", "show_results": "after_vote", "is_visible": "on"})
    s = Survey.objects.get(title="Pick a day")
    assert r.status_code == 302 and s.published_at and Notification.objects.filter(user=enrolled, url=f"/surveys/{s.pk}/").count() == 1
    c.post(reverse("surveys:edit", args=[s.pk]), {"kind": "poll", "title": "Pick a day 2", "show_results": "after_vote", "is_visible": "on"})
    assert Notification.objects.filter(user=enrolled).count() == 1  # editing does not notify again


def test_question_rules(lecturer, course):
    s = Survey.objects.create(course=course, title="P", kind="poll")
    c = as_user(lecturer)
    bad = c.post(reverse("surveys:question-new", args=[s.pk]), {"text": "Q", "kind": "single", "choices": "only one", "required": "on"})
    assert bad.status_code == 200 and not s.questions.exists()
    c.post(reverse("surveys:question-new", args=[s.pk]), {"text": "Q", "kind": "single", "choices": "a\nb", "required": "on"})
    assert s.questions.count() == 1
    c.post(reverse("surveys:question-new", args=[s.pk]), {"text": "Q2", "kind": "text"})
    assert s.questions.count() == 1  # a poll has one question


def test_questions_lock_after_answers(lecturer, enrolled, survey):
    as_user(enrolled).post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey))
    q = survey.questions.first()
    c = as_user(lecturer)
    c.post(reverse("surveys:question-delete", args=[q.pk]))
    assert SurveyQuestion.objects.filter(pk=q.pk).exists()
    c.post(reverse("surveys:question-edit", args=[q.pk]), {"text": "Changed", "kind": "single", "choices": "a\nb"})
    assert SurveyQuestion.objects.get(pk=q.pk).text == "Pace?"


def test_export_is_safe_and_anonymous_has_no_names(lecturer, enrolled, survey):
    as_user(enrolled).post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey, **{f"q{list(survey.questions.all())[3].pk}": "=1+1"}))
    body = as_user(lecturer).get(reverse("surveys:export", args=[survey.pk])).content.decode()
    assert "'=1+1" in body and "Amal" in body
    survey.anonymous = True
    survey.save()
    anon = as_user(lecturer).get(reverse("surveys:export", args=[survey.pk])).content.decode()
    assert "Amal" not in anon and "s2026-0142" not in anon


def test_deleting_removes_answers(lecturer, enrolled, survey):
    as_user(enrolled).post(reverse("surveys:student-detail", args=[survey.pk]), answers(survey))
    as_user(lecturer).post(reverse("surveys:delete", args=[survey.pk]))
    assert not Survey.objects.exists() and not Answer.objects.exists() and not Submission.objects.exists()


def test_module_switch_hides_everything(enrolled, survey):
    ModuleSetting.objects.create(key="surveys", enabled=False)
    c = as_user(enrolled)
    assert c.get(reverse("surveys:student-list")).status_code == 404
    assert c.get(reverse("surveys:student-detail", args=[survey.pk])).status_code == 404
