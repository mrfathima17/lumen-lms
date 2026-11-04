from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.attendance.models import AttendanceRecord, AttendanceSession
from apps.completion import services
from apps.completion.models import Certificate, CompletionRule, new_code
from apps.core.models import AuditLog
from apps.messaging.models import Notification
from apps.quizzes.models import Attempt, Question, Quiz


def as_user(u):
    c = Client()
    c.force_login(u)
    return c


def make_assignment(course, title="A1", visible=True):
    return Assignment.objects.create(course=course, title=title, due_at=timezone.now() + timedelta(days=3), max_mark=100, is_visible=visible)


def submit(a, student):
    return Submission.objects.create(assignment=a, student=student, file="x.pdf", submitted_at=timezone.now())


# ---------- evaluation ----------

def test_no_rules_means_not_tracked(enrolled, course):
    r = services.evaluate(course, enrolled)
    assert r["tracked"] is False and r["complete"] is False
    assert services.award_if_complete(course, enrolled) is None


def test_assignment_rule_counts_only_visible_assignments(enrolled, course):
    rule = services.rule_for(course)
    rule.require_assignments = True
    rule.save()
    a1, a2 = make_assignment(course, "A1"), make_assignment(course, "A2")
    make_assignment(course, "Hidden", visible=False)
    submit(a1, enrolled)
    r = services.evaluate(course, enrolled, rule)
    assert not r["complete"] and r["checks"][0]["detail"] == "1 of 2"
    submit(a2, enrolled)
    assert services.evaluate(course, enrolled, rule)["complete"]


def test_attendance_rule(enrolled, course):
    rule = services.rule_for(course)
    rule.min_attendance_percent = 75
    rule.save()
    assert services.evaluate(course, enrolled, rule)["checks"][0]["detail"] == "Nothing recorded yet"
    for i, st in enumerate(["present", "present", "late", "absent"]):
        s = AttendanceSession.objects.create(course=course, title=f"S{i}", held_on=timezone.localdate() - timedelta(days=i))
        AttendanceRecord.objects.create(session=s, student=enrolled, status=st)
    assert services.evaluate(course, enrolled, rule)["complete"]  # 3 of 4 = 75%
    rule.min_attendance_percent = 80
    assert not services.evaluate(course, enrolled, rule)["complete"]


def test_quiz_rule_uses_best_graded_attempt_and_counts_missing_as_zero(enrolled, course):
    rule = services.rule_for(course)
    rule.min_quiz_percent = 50
    rule.save()
    assert services.evaluate(course, enrolled, rule)["checks"][0]["detail"] == "No quizzes yet"
    q1, q2 = Quiz.objects.create(course=course, title="Q1"), Quiz.objects.create(course=course, title="Q2")
    for q in (q1, q2):
        Question.objects.create(quiz=q, kind="mcq", text="?", marks=10, position=1)
    now = timezone.now()
    Attempt.objects.create(quiz=q1, student=enrolled, number=1, started_at=now, status="graded", score=Decimal("4"))
    Attempt.objects.create(quiz=q1, student=enrolled, number=2, started_at=now, status="graded", score=Decimal("10"))
    r = services.evaluate(course, enrolled, rule)
    assert r["checks"][0]["detail"] == "50.0%" and r["complete"]  # (100% + 0%) / 2
    Attempt.objects.filter(score=10).delete()
    assert not services.evaluate(course, enrolled, rule)["complete"]  # best is now 4/10 -> 20% average


def test_all_rules_must_be_met(enrolled, course):
    rule = services.rule_for(course)
    rule.require_assignments = True
    rule.min_attendance_percent = 50
    rule.save()
    a = make_assignment(course)
    submit(a, enrolled)
    r = services.evaluate(course, enrolled, rule)
    assert r["met"] == 1 and r["total"] == 2 and not r["complete"] and r["percent"] == 50


# ---------- certificates ----------

def complete_setup(course, student):
    rule = services.rule_for(course)
    rule.require_assignments = True
    rule.save()
    submit(make_assignment(course), student)
    return rule


def test_certificate_issued_once_with_frozen_names_and_notification(enrolled, course):
    complete_setup(course, enrolled)
    cert = services.award_if_complete(course, enrolled)
    assert cert and len(cert.code) == 14 and cert.student_name == "Amal Karunaratne" and cert.course_code == "CS201"
    assert services.award_if_complete(course, enrolled).pk == cert.pk
    assert Certificate.objects.count() == 1 and Notification.objects.filter(user=enrolled, text__contains="certificate").count() == 1
    course.title = "Renamed"
    course.save()
    cert.refresh_from_db()
    assert cert.course_title == "Database Systems"


def test_auto_certificate_off_waits_for_lecturer(enrolled, course):
    rule = complete_setup(course, enrolled)
    rule.auto_certificate = False
    rule.save()
    assert services.award_if_complete(course, enrolled, rule) is None
    assert services.issue_all(course) == 1 and services.issue_all(course) == 0


def test_revoked_certificate_is_not_recreated(enrolled, course):
    complete_setup(course, enrolled)
    cert = services.award_if_complete(course, enrolled)
    services.revoke(cert)
    assert services.award_if_complete(course, enrolled).revoked_at is not None
    assert Certificate.objects.count() == 1


def test_codes_are_unique_and_unambiguous():
    codes = {new_code() for _ in range(500)}
    assert len(codes) == 500 and all(not set(c) & set("01OI") for c in codes)


def test_command_issues_for_auto_courses_only(enrolled, course):
    from django.core.management import call_command

    complete_setup(course, enrolled)
    call_command("issue_certificates")
    assert Certificate.objects.count() == 1


# ---------- views ----------

def test_student_pages_and_lazy_award(enrolled, course):
    complete_setup(course, enrolled)
    c = as_user(enrolled)
    assert b"Completed" in c.get(reverse("completion:mine")).content
    assert Certificate.objects.count() == 1
    html = c.get(reverse("completion:mine-course", args=[course.pk])).content
    assert b"Download your certificate" in html
    assert b"CS201" in c.get(reverse("completion:certificates")).content


def test_student_cannot_open_unenrolled_course_progress(student, course):
    assert as_user(student).get(reverse("completion:mine-course", args=[course.pk])).status_code == 404


def test_staff_cannot_use_student_pages_and_students_cannot_manage(enrolled, lecturer, course):
    assert as_user(lecturer).get(reverse("completion:mine")).status_code == 403
    assert as_user(lecturer).get(reverse("completion:certificates")).status_code == 403
    assert as_user(enrolled).get(reverse("completion:manage", args=[course.pk])).status_code == 403
    assert as_user(enrolled).get(reverse("completion:manage-list")).status_code == 403


def test_lecturer_saves_rules_and_sees_roster(enrolled, lecturer, course):
    c = as_user(lecturer)
    r = c.post(reverse("completion:manage", args=[course.pk]), {"require_assignments": "on", "min_quiz_percent": "", "min_attendance_percent": "80", "min_final_percent": "", "auto_certificate": "on"})
    assert r.status_code == 302
    rule = CompletionRule.objects.get(course=course)
    assert rule.require_assignments and rule.min_attendance_percent == 80 and rule.min_quiz_percent is None
    assert b"Amal" in c.get(reverse("completion:manage", args=[course.pk])).content
    assert AuditLog.objects.filter(action="completion_rule_saved").exists()


def test_rule_percent_validation(lecturer, course):
    r = as_user(lecturer).post(reverse("completion:manage", args=[course.pk]), {"min_quiz_percent": "150"})
    assert r.status_code == 200 and not CompletionRule.objects.filter(min_quiz_percent=150).exists()


def test_other_lecturer_cannot_manage(course, make_user):
    other = make_user("other", "lecturer")
    c = as_user(other)
    assert c.get(reverse("completion:manage", args=[course.pk])).status_code == 403
    assert c.post(reverse("completion:issue-all", args=[course.pk])).status_code == 403


def test_issue_all_and_revoke(enrolled, lecturer, course):
    rule = complete_setup(course, enrolled)
    rule.auto_certificate = False
    rule.save()
    c = as_user(lecturer)
    assert c.post(reverse("completion:issue-all", args=[course.pk])).status_code == 302
    cert = Certificate.objects.get()
    assert AuditLog.objects.filter(action="certificates_issued", detail="1 issued").exists()
    c.post(reverse("completion:revoke", args=[cert.pk]))
    cert.refresh_from_db()
    assert not cert.is_valid and AuditLog.objects.filter(action="certificate_revoked").exists()
    assert as_user(enrolled).post(reverse("completion:revoke", args=[cert.pk])).status_code == 403


def test_pdf_download_permissions_and_content(enrolled, lecturer, course, make_user):
    complete_setup(course, enrolled)
    cert = services.award_if_complete(course, enrolled)
    url = reverse("completion:pdf", args=[cert.code])
    r = as_user(enrolled).get(url)
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert as_user(lecturer).get(url).status_code == 200
    assert as_user(make_user("s9", "student")).get(url).status_code == 404
    assert as_user(make_user("l9", "lecturer")).get(url).status_code == 404
    assert Client().get(url).status_code == 302
    assert as_user(enrolled).get(reverse("completion:pdf", args=[cert.code.lower()])).status_code == 200  # codes are case-insensitive


def test_revoked_pdf_is_stamped(enrolled, course):
    from apps.completion.pdf import build_pdf

    complete_setup(course, enrolled)
    cert = services.award_if_complete(course, enrolled)
    ok = build_pdf(cert, "Lumen", "http://x/verify/")
    services.revoke(cert)
    cert.refresh_from_db()
    assert len(build_pdf(cert, "Lumen", "http://x/verify/")) != len(ok)


def test_public_verify_page(enrolled, course):
    complete_setup(course, enrolled)
    cert = services.award_if_complete(course, enrolled)
    anon = Client()
    r = anon.get(reverse("completion:verify", args=[cert.code]))
    assert r.status_code == 200 and b"Certificate is valid" in r.content and b"Amal Karunaratne" in r.content
    assert b"@" not in r.content.split(b"<main")[1]  # no email or other personal data on the public page
    assert b"valid" in anon.get(reverse("completion:verify", args=[cert.code.lower()])).content
    assert anon.get(reverse("completion:verify", args=["NOPE-NOPE-NOPE"])).status_code == 404
    services.revoke(cert)
    assert b"revoked" in anon.get(reverse("completion:verify", args=[cert.code])).content.lower()


def test_nav_links(enrolled, lecturer):
    h = as_user(enrolled).get(reverse("accounts:student-dashboard")).content
    assert reverse("completion:mine").encode() in h and reverse("completion:certificates").encode() in h
    assert reverse("completion:manage-list").encode() in as_user(lecturer).get(reverse("accounts:lecturer-dashboard")).content
