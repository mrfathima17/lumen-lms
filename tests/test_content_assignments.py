from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.assignments import services
from apps.assignments.models import Assignment, Extension, Submission
from apps.content.models import Resource
from apps.core.models import SiteSettings
from apps.courses.models import Topic


def f(name="work.pdf", data=b"%PDF-1.4 test"):
    return SimpleUploadedFile(name, data)


@pytest.fixture
def topic(course):
    return Topic.objects.create(course=course, title="Week 1")


@pytest.fixture
def assignment(course, topic):
    return Assignment.objects.create(course=course, topic=topic, title="ER Diagram", due_at=timezone.now() + timedelta(days=2), max_mark=100)


# ---- pure rules ----

def test_days_late_counts_started_days():
    due = timezone.now()
    assert services.days_late(due, due - timedelta(hours=1)) == 0
    assert services.days_late(due, due) == 0
    assert services.days_late(due, due + timedelta(minutes=1)) == 1
    assert services.days_late(due, due + timedelta(days=1)) == 1
    assert services.days_late(due, due + timedelta(days=1, seconds=1)) == 2


def test_penalty_uses_site_setting_and_caps_at_100(db):
    assert services.penalty_for(2) == 20  # default 10% per day
    s = SiteSettings.load(); s.late_penalty_percent_per_day = 25; s.save()
    assert services.penalty_for(2) == 50 and services.penalty_for(9) == 100


def test_apply_penalty_rounding():
    assert services.apply_penalty(Decimal("86"), 10) == Decimal("77.40")
    assert services.apply_penalty(Decimal("33.33"), 15) == Decimal("28.33")
    assert services.apply_penalty(Decimal("50"), 100) == Decimal("0.00")


def test_extension_only_counts_if_later(assignment, enrolled, student):
    assert services.effective_due(assignment, student) == assignment.due_at
    Extension.objects.create(assignment=assignment, student=student, due_at=assignment.due_at + timedelta(days=3))
    assert services.effective_due(assignment, student) == assignment.due_at + timedelta(days=3)
    Extension.objects.filter(student=student).update(due_at=assignment.due_at - timedelta(days=1))
    assert services.effective_due(assignment, student) == assignment.due_at


# ---- submitting ----

def test_submit_on_time_then_replace(assignment, enrolled, student):
    s = services.submit(assignment, student, f("a.pdf"))
    assert s.late_days == 0 and s.status == "submitted"
    s2 = services.submit(assignment, student, f("b.pdf"), "second try")
    assert s2.pk == s.pk and Submission.objects.count() == 1 and s2.comment == "second try"


def test_late_submission_marked_and_penalised(assignment, enrolled, student, lecturer):
    when = assignment.due_at + timedelta(days=1, hours=2)
    s = services.submit(assignment, student, f(), now=when)
    assert s.late_days == 2
    services.grade(s, Decimal("80"), "ok", lecturer)
    s.refresh_from_db()
    assert s.penalty_percent == 20 and s.final_mark == Decimal("64.00") and s.status == "graded"


def test_extension_removes_lateness(assignment, enrolled, student):
    Extension.objects.create(assignment=assignment, student=student, due_at=assignment.due_at + timedelta(days=5))
    s = services.submit(assignment, student, f(), now=assignment.due_at + timedelta(days=1))
    assert s.late_days == 0


def test_late_refused_when_not_allowed(assignment, enrolled, student):
    assignment.allow_late = False; assignment.save()
    with pytest.raises(services.SubmissionError):
        services.submit(assignment, student, f(), now=assignment.due_at + timedelta(minutes=5))


def test_cannot_submit_when_not_enrolled_or_hidden(assignment, student, enrolled):
    with pytest.raises(services.SubmissionError):
        services.submit(assignment, student.__class__.objects.create_user("x", password="p", role="student"), f())
    assignment.is_visible = False; assignment.save()
    with pytest.raises(services.SubmissionError):
        services.submit(assignment, student, f())


def test_graded_submission_is_locked(assignment, enrolled, student, lecturer):
    s = services.submit(assignment, student, f())
    services.grade(s, 70, "", lecturer)
    with pytest.raises(services.SubmissionError):
        services.submit(assignment, student, f("new.pdf"))


def test_grade_bounds(assignment, enrolled, student, lecturer):
    s = services.submit(assignment, student, f())
    for bad in (-1, 101):
        with pytest.raises(ValueError):
            services.grade(s, bad, "", lecturer)


# ---- views ----

def test_student_submits_through_view(client, assignment, enrolled, student):
    client.force_login(student)
    url = reverse("assignments:detail", args=[assignment.pk])
    r = client.post(url, {"file": f(), "comment": "hi", "own_work": "on"})
    assert r.status_code == 302 and Submission.objects.filter(student=student).exists()
    assert b"Awaiting grading" in client.get(url).content


def test_bad_upload_rejected(client, assignment, enrolled, student):
    client.force_login(student)
    url = reverse("assignments:detail", args=[assignment.pk])
    for upload in (f("virus.exe"), f("big.pdf", b"x" * (21 * 1024 * 1024))):
        r = client.post(url, {"file": upload})
        assert r.status_code == 200 and not Submission.objects.exists()


def test_other_student_cannot_see_or_download(client, assignment, enrolled, student, make_user):
    s = services.submit(assignment, student, f())
    client.force_login(make_user("nosy", "student"))
    assert client.get(reverse("assignments:detail", args=[assignment.pk])).status_code == 403
    assert client.get(reverse("assignments:download", args=[s.pk])).status_code == 403


def test_owner_and_lecturer_can_download(client, assignment, enrolled, student, lecturer):
    s = services.submit(assignment, student, f("mine.pdf", b"CONTENT"))
    url = reverse("assignments:download", args=[s.pk])
    for u in (student, lecturer):
        client.force_login(u)
        r = client.get(url)
        assert r.status_code == 200 and b"".join(r.streaming_content) == b"CONTENT"
        assert "attachment" in r["Content-Disposition"] and r["X-Content-Type-Options"] == "nosniff"


def test_accel_redirect_mode(client, assignment, enrolled, student, settings):
    s = services.submit(assignment, student, f())
    settings.USE_ACCEL_REDIRECT = True
    client.force_login(student)
    r = client.get(reverse("assignments:download", args=[s.pk]))
    assert r["X-Accel-Redirect"] == f"/media/{s.file.name}"


def test_lecturer_creates_edits_and_grades(client, course, lecturer, enrolled, student, topic):
    client.force_login(lecturer)
    due = (timezone.localtime() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(reverse("assignments:new", args=[course.pk]), {"title": "Lab 1", "topic": topic.pk, "due_at": due, "max_mark": "50", "allow_late": "on", "is_visible": "on"})
    assert r.status_code == 302
    a = Assignment.objects.get(title="Lab 1")
    s = services.submit(a, student, f())
    r = client.post(reverse("assignments:grade", args=[s.pk]), {"raw_mark": "60", "feedback": "x"})
    assert r.status_code == 200 and b"cannot be above 50" in r.content
    r = client.post(reverse("assignments:grade", args=[s.pk]), {"raw_mark": "45", "feedback": "Good"})
    assert r.status_code == 302
    s.refresh_from_db()
    assert s.final_mark == Decimal("45.00") and s.graded_by == lecturer
    client.force_login(student)
    body = client.get(reverse("assignments:detail", args=[a.pk])).content
    assert b"45" in body and b"Good" in body


def test_other_lecturer_and_student_cannot_manage(client, assignment, enrolled, student, make_user):
    for u in (student, make_user("intruder", "lecturer")):
        client.force_login(u)
        assert client.get(reverse("assignments:submissions", args=[assignment.pk])).status_code == 403
        assert client.get(reverse("assignments:edit", args=[assignment.pk])).status_code == 403
        assert client.get(reverse("assignments:extensions", args=[assignment.pk])).status_code == 403


def test_extension_form_validates(client, assignment, enrolled, student, lecturer):
    client.force_login(lecturer)
    url = reverse("assignments:extensions", args=[assignment.pk])
    early = (timezone.localtime(assignment.due_at) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    assert client.post(url, {"student": student.pk, "due_at": early}).status_code == 200
    later = (timezone.localtime(assignment.due_at) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    assert client.post(url, {"student": student.pk, "due_at": later}).status_code == 302
    assert Extension.objects.filter(student=student).count() == 1


def test_overview_pages(client, assignment, enrolled, student, lecturer):
    client.force_login(student)
    assert b"ER Diagram" in client.get(reverse("assignments:overview")).content
    client.force_login(lecturer)
    assert b"ER Diagram" in client.get(reverse("assignments:overview")).content


# ---- materials ----

def test_lecturer_adds_file_and_link(client, course, lecturer, topic):
    client.force_login(lecturer)
    url = reverse("content:add", args=[course.pk])
    assert client.post(url, {"topic": topic.pk, "kind": "file", "title": "Slides", "file": f("slides.pdf")}).status_code == 302
    assert client.post(url, {"topic": topic.pk, "kind": "link", "title": "Docs", "url": "https://example.com"}).status_code == 302
    assert client.post(url, {"topic": topic.pk, "kind": "file", "title": "Empty"}).status_code == 200
    assert Resource.objects.count() == 2


def test_add_material_needs_a_topic(client, course, lecturer):
    client.force_login(lecturer)
    r = client.get(reverse("content:add", args=[course.pk]))
    assert r.status_code == 302


def test_material_visibility_and_download_rules(client, course, lecturer, enrolled, student, topic, make_user):
    r = Resource.objects.create(topic=topic, kind="file", title="Slides", file=f("s.pdf", b"SLIDES"))
    dl = reverse("content:download", args=[r.pk])
    client.force_login(student)
    assert client.get(dl).status_code == 200
    assert b"Slides" in client.get(reverse("courses:detail", args=[course.pk])).content
    client.force_login(make_user("outsider", "student"))
    assert client.get(dl).status_code == 403
    client.force_login(lecturer)
    client.post(reverse("content:action", args=[r.pk, "toggle"]))
    client.force_login(student)
    assert client.get(dl).status_code == 403
    assert b"Slides" not in client.get(reverse("courses:detail", args=[course.pk])).content
    client.force_login(lecturer)
    assert client.get(dl).status_code == 200


def test_delete_material_removes_file(client, course, lecturer, topic):
    r = Resource.objects.create(topic=topic, kind="file", title="Old", file=f("old.pdf"))
    path = r.file.path
    client.force_login(lecturer)
    client.post(reverse("content:action", args=[r.pk, "delete"]))
    import os
    assert not Resource.objects.exists() and not os.path.exists(path)


def test_student_cannot_manage_materials(client, course, enrolled, student, topic):
    r = Resource.objects.create(topic=topic, kind="link", title="L", url="https://example.com")
    client.force_login(student)
    assert client.get(reverse("content:add", args=[course.pk])).status_code == 403
    assert client.post(reverse("content:action", args=[r.pk, "delete"])).status_code == 403
    assert Resource.objects.exists()


def test_download_uses_original_filename(client, assignment, enrolled, student):
    s = services.submit(assignment, student, f("my report.pdf"))
    client.force_login(student)
    r = client.get(reverse("assignments:download", args=[s.pk]))
    assert 'filename="my_report.pdf"' in r["Content-Disposition"]
    assert s.original_name == "my_report.pdf"


def test_submission_needs_own_work_tick(client, assignment, enrolled, student):
    client.force_login(student)
    r = client.post(reverse("assignments:detail", args=[assignment.pk]), {"file": f(), "comment": ""})
    assert r.status_code == 200 and b"confirm this is your own work" in r.content
    assert not Submission.objects.filter(student=student).exists()


def test_mark_material_done_toggles(client, topic, enrolled, student):
    from apps.content.models import Resource, ResourceDone

    res = Resource.objects.create(topic=topic, kind="link", title="Handbook", url="https://example.com")
    client.force_login(student)
    url = reverse("content:done", args=[res.pk])
    assert client.post(url).status_code == 302 and ResourceDone.objects.filter(resource=res, user=student).count() == 1
    assert b"Done" in client.get(reverse("content:view", args=[res.pk])).content
    client.post(url)
    assert not ResourceDone.objects.filter(resource=res).exists()


def test_assignment_file_type_and_size_rules(client, assignment, enrolled, student):
    assignment.allowed_types = "pdf, zip"
    assignment.max_file_mb = 1
    assignment.save()
    client.force_login(student)
    url = reverse("assignments:detail", args=[assignment.pk])
    r = client.post(url, {"file": f("notes.txt", b"x"), "own_work": "on"})
    assert r.status_code == 200 and b"accepts only: PDF, ZIP" in r.content
    r = client.post(url, {"file": f("big.pdf", b"0" * (1024 * 1024 + 1)), "own_work": "on"})
    assert r.status_code == 200 and b"larger than 1 MB" in r.content
    assert not Submission.objects.exists()
    assert client.post(url, {"file": f(), "own_work": "on"}).status_code == 302


def test_lecturer_sets_assignment_file_rules(client, course, lecturer):
    client.force_login(lecturer)
    url = reverse("assignments:create", args=[course.pk]) if False else None
    from apps.assignments.forms import AssignmentForm
    base = {"title": "T", "description": "d", "due_at": "2030-01-01T10:00", "max_mark": "100", "max_file_mb": "5"}
    assert not AssignmentForm({**base, "allowed_types": "exe"}, course=course).is_valid()
    assert not AssignmentForm({**base, "allowed_types": "pdf", "max_file_mb": "99"}, course=course).is_valid()
    form = AssignmentForm({**base, "allowed_types": ".PDF; docx"}, course=course)
    assert form.is_valid() and form.cleaned_data["allowed_types"] == "pdf, docx"


def test_material_saved_as_draft_is_hidden(client, course, lecturer, topic):
    client.force_login(lecturer)
    r = client.post(reverse("content:add", args=[course.pk]), {"kind": "link", "title": "Soon", "topic": topic.pk, "url": "https://example.com", "draft": "1"})
    assert r.status_code == 302
    assert Resource.objects.get(title="Soon").is_visible is False
