from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.assignments import rubric
from apps.assignments.models import Assignment, RubricCriterion, RubricScore, Submission


def as_user(u):
    c = Client()
    c.force_login(u)
    return c


@pytest.fixture
def assignment(course):
    return Assignment.objects.create(course=course, title="Report", due_at=timezone.now() + timedelta(days=2), max_mark=50)


@pytest.fixture
def rubric_set(assignment):
    a = rubric.save_criterion(assignment, None, "Content", "", rubric.parse_levels("Great | 10 | all there\nOkay | 6\nPoor | 0")[0])
    b = rubric.save_criterion(assignment, None, "Style", "", rubric.parse_levels("Great | 5\nPoor | 1")[0])
    return a, b


@pytest.fixture
def sub(assignment, enrolled):
    return Submission.objects.create(assignment=assignment, student=enrolled, file=SimpleUploadedFile("w.pdf", b"%PDF-1.4"), submitted_at=timezone.now())


def test_parse_levels_rules():
    ok, err = rubric.parse_levels("A | 10 | best\nB | 5.5\n\nC | 0")
    assert err is None and [lv["points"] for lv in ok] == [Decimal("10"), Decimal("5.5"), Decimal("0")] and ok[0]["description"] == "best"
    for bad in ["A | 10", "A | x\nB | 1", "A\nB | 1", "A | 1\nB | 1", "A | -1\nB | 2", "A | 1.234\nB | 2", "|1\nB|2", " | | ", "a|1|b\n" * 1 + "c|2\n" * 0]:
        assert rubric.parse_levels(bad)[1], bad
    assert rubric.parse_levels("\n".join(f"L{i} | {i}" for i in range(7)))[1]


def test_total_and_scaling(assignment, rubric_set):
    assert rubric.total_points(assignment) == 15
    assert rubric.scaled_mark(Decimal("11"), assignment) == Decimal("36.67")
    assert rubric.scaled_mark(15, assignment) == 50


def test_grading_with_rubric_sets_mark_scores_and_penalty(assignment, rubric_set, sub, lecturer):
    a, b = rubric_set
    sub.late_days = 1
    sub.save()
    picks = {a.pk: (a.levels.get(label="Okay").pk, "needs examples"), b.pk: (b.levels.get(label="Great").pk, "")}
    rubric.grade(sub, picks, "Fine work", lecturer)
    sub.refresh_from_db()
    assert sub.raw_mark == Decimal("36.67") and sub.penalty_percent == 10 and sub.final_mark == Decimal("33.00") and sub.status == "graded"
    assert RubricScore.objects.filter(submission=sub).count() == 2 and RubricScore.objects.get(criterion=a).comment == "needs examples"


def test_every_row_needs_a_level(assignment, rubric_set, sub, lecturer):
    a, b = rubric_set
    with pytest.raises(rubric.RubricError):
        rubric.grade(sub, {a.pk: (a.levels.first().pk, "")}, "", lecturer)
    with pytest.raises(rubric.RubricError):  # a level that belongs to another row
        rubric.grade(sub, {a.pk: (b.levels.first().pk, ""), b.pk: (b.levels.first().pk, "")}, "", lecturer)
    sub.refresh_from_db()
    assert sub.status == "submitted" and not RubricScore.objects.exists()


def test_regrading_replaces_scores(assignment, rubric_set, sub, lecturer):
    a, b = rubric_set
    rubric.grade(sub, {a.pk: (a.levels.get(label="Poor").pk, ""), b.pk: (b.levels.get(label="Poor").pk, "")}, "", lecturer)
    rubric.grade(sub, {a.pk: (a.levels.get(label="Great").pk, ""), b.pk: (b.levels.get(label="Great").pk, "")}, "", lecturer)
    sub.refresh_from_db()
    assert sub.final_mark == 50 and RubricScore.objects.filter(submission=sub).count() == 2


def test_grade_page_flow(assignment, rubric_set, sub, lecturer):
    a, b = rubric_set
    c = as_user(lecturer)
    url = reverse("assignments:grade", args=[sub.pk])
    page = c.get(url).content
    assert b"<h2>Rubric</h2>" in page and b'name="level%d"' % a.pk in page
    r = c.post(url, {f"level{a.pk}": a.levels.get(label="Great").pk})  # second row missing
    assert r.status_code == 200 and b"Pick a level" in r.content
    r = c.post(url, {f"level{a.pk}": a.levels.get(label="Great").pk, f"level{b.pk}": b.levels.get(label="Poor").pk, "feedback": "ok"})
    assert r.status_code == 302
    sub.refresh_from_db()
    assert sub.final_mark == Decimal("36.67")


def test_student_sees_breakdown(assignment, rubric_set, sub, lecturer, enrolled):
    a, b = rubric_set
    rubric.grade(sub, {a.pk: (a.levels.get(label="Okay").pk, "add detail"), b.pk: (b.levels.get(label="Great").pk, "")}, "Well done", lecturer)
    page = as_user(enrolled).get(reverse("assignments:detail", args=[assignment.pk])).content.decode()
    assert "Content" in page and "Okay" in page and "add detail" in page and "Well done" in page


def test_plain_grading_still_works_without_rubric(assignment, sub, lecturer):
    r = as_user(lecturer).post(reverse("assignments:grade", args=[sub.pk]), {"raw_mark": "40", "feedback": "x"})
    sub.refresh_from_db()
    assert r.status_code == 302 and sub.final_mark == 40


def test_rubric_locks_after_marking(assignment, rubric_set, sub, lecturer):
    a, b = rubric_set
    rubric.grade(sub, {a.pk: (a.levels.first().pk, ""), b.pk: (b.levels.first().pk, "")}, "", lecturer)
    c = as_user(lecturer)
    c.post(reverse("assignments:criterion-delete", args=[a.pk]))
    assert RubricCriterion.objects.filter(pk=a.pk).exists()
    c.post(reverse("assignments:criterion-edit", args=[a.pk]), {"title": "Changed", "levels": "X | 1\nY | 2"})
    a.refresh_from_db()
    assert a.title == "Content"
    c.post(reverse("assignments:criterion-new", args=[assignment.pk]), {"title": "New", "levels": "X | 1\nY | 2"})
    assert assignment.criteria.count() == 2


def test_criterion_crud(assignment, lecturer):
    c = as_user(lecturer)
    bad = c.post(reverse("assignments:criterion-new", args=[assignment.pk]), {"title": "T", "levels": "only | 1"})
    assert bad.status_code == 200 and not assignment.criteria.exists()
    c.post(reverse("assignments:criterion-new", args=[assignment.pk]), {"title": "T", "levels": "A | 2 | good\nB | 1"})
    crit = assignment.criteria.get()
    assert [lv.label for lv in crit.levels.all()] == ["A", "B"]
    page = c.get(reverse("assignments:criterion-edit", args=[crit.pk])).content.decode()
    assert "A | 2 | good" in page
    c.post(reverse("assignments:criterion-edit", args=[crit.pk]), {"title": "T2", "levels": "A | 3\nB | 1\nC | 0"})
    crit.refresh_from_db()
    assert crit.title == "T2" and crit.levels.count() == 3
    c.post(reverse("assignments:criterion-delete", args=[crit.pk]))
    assert not assignment.criteria.exists()


def test_copy_rubric(assignment, rubric_set, course, lecturer):
    other = Assignment.objects.create(course=course, title="Report 2", due_at=timezone.now() + timedelta(days=9), max_mark=20)
    c = as_user(lecturer)
    c.post(reverse("assignments:rubric-copy", args=[other.pk]), {"source": assignment.pk})
    assert other.criteria.count() == 2 and RubricCriterion.objects.filter(assignment=other).first().levels.count() == 3
    c.post(reverse("assignments:rubric-copy", args=[other.pk]), {"source": assignment.pk})  # already has one
    assert other.criteria.count() == 2


def test_permissions(assignment, rubric_set, sub, enrolled, make_user):
    s = as_user(enrolled)
    crit = rubric_set[0]
    for name, args in [("assignments:rubric", [assignment.pk]), ("assignments:criterion-new", [assignment.pk]), ("assignments:criterion-edit", [crit.pk]), ("assignments:grade", [sub.pk])]:
        assert s.get(reverse(name, args=args)).status_code == 403
    assert s.post(reverse("assignments:criterion-delete", args=[crit.pk])).status_code == 403
    other = as_user(make_user("lect2", "lecturer"))
    assert other.get(reverse("assignments:rubric", args=[assignment.pk])).status_code == 403
    assert other.post(reverse("assignments:criterion-delete", args=[crit.pk])).status_code == 403
    assert RubricCriterion.objects.filter(pk=crit.pk).exists()
