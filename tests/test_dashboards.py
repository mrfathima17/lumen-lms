from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.completion.models import CompletionRule
from apps.core.models import AllowedNetwork, AuditLog
from apps.courses.models import Course, Enrolment
from apps.grading.models import CourseResult
from apps.messaging.models import Announcement, ForumTopic
from apps.quizzes.models import Quiz
from apps.schedule.models import TimetableSlot


def login(client, user):
    client.force_login(user)
    return client


# ---------------- student ----------------

def test_student_dashboard_is_filled_in(client, course, enrolled, lecturer):
    now = timezone.now()
    Assignment.objects.create(course=course, title="ER Diagram", due_at=now + timedelta(hours=20))
    Assignment.objects.create(course=course, title="Far away", due_at=now + timedelta(days=12))
    Quiz.objects.create(course=course, title="Quiz 3", closes_at=now + timedelta(days=3))
    Announcement.objects.create(course=course, author=lecturer, title="Mid-term schedule", body="x")
    CompletionRule.objects.create(course=course, require_assignments=True)
    html = login(client, enrolled).get(reverse("accounts:student-dashboard")).content.decode()
    assert "Good " in html and "Amal" in html
    assert "1 assignment due this week and 1 quiz open" in html
    assert "ER Diagram" in html and "Quiz 3" in html and "Mid-term schedule" in html
    assert "Database Systems" in html and "Nimal Perera" in html
    assert "Due tomorrow" in html or "Due today" in html
    assert 'aria-valuenow="0"' in html  # tracked course, nothing submitted yet


def test_student_dashboard_empty_states(client, student):
    html = login(client, student).get(reverse("accounts:student-dashboard")).content.decode()
    assert "Nothing is due this week." in html and "No courses yet" in html and "No announcements yet" in html
    assert "No classes on your timetable." in html and "Cumulative GPA" in html


def test_student_gpa_shows_when_results_are_published(client, course, enrolled):
    CourseResult.objects.create(course=course, student=enrolled, percent=82, letter="A-", points=Decimal("3.70"), credits=4, published_at=timezone.now())
    html = login(client, enrolled).get(reverse("accounts:student-dashboard")).content.decode()
    assert "<b>3.70</b>" in html


def test_student_sees_todays_class_and_the_next_one(client, course, enrolled):
    now = timezone.localtime()
    TimetableSlot.objects.create(course=course, weekday=now.weekday(), start_time=time(0, 0), end_time=time(23, 59), room="B-204")
    TimetableSlot.objects.create(course=course, weekday=(now.weekday() + 1) % 7, start_time=time(9, 0), end_time=time(11, 0), room="Lab 3")
    html = login(client, enrolled).get(reverse("accounts:student-dashboard")).content.decode()
    assert "B-204" in html and "Next: Database Systems" in html and "Lab 3" in html


def test_student_does_not_see_hidden_or_other_courses(client, course, student, make_user):
    other = Course.objects.create(code="ZZ1", title="Secret", credits=3)
    Enrolment.objects.create(course=other, user=make_user("other", "student"))
    html = login(client, student).get(reverse("accounts:student-dashboard")).content.decode()
    assert "Secret" not in html


@pytest.mark.parametrize("name", ["accounts:student-dashboard", "accounts:lecturer-dashboard", "accounts:admin-overview"])
def test_dashboards_are_for_their_own_role(client, student, name):
    login(client, student)
    assert client.get(reverse(name)).status_code == (200 if name == "accounts:student-dashboard" else 403)


# ---------------- lecturer ----------------

def test_lecturer_dashboard_numbers_and_tables(client, course, enrolled, lecturer):
    now = timezone.now()
    a = Assignment.objects.create(course=course, title="ER Diagram", due_at=now + timedelta(days=2))
    Submission.objects.create(assignment=a, student=enrolled, file="x.pdf", submitted_at=now)
    Quiz.objects.create(course=course, title="Quiz 3", closes_at=now + timedelta(days=3))
    Quiz.objects.create(course=course, title="Quiz 4", is_visible=False, is_enabled=False)
    html = login(client, lecturer).get(reverse("accounts:lecturer-dashboard")).content.decode()
    assert "Welcome, Nimal Perera" in html and "CS201 · Database Systems" in html
    for label in ("Students", "Submissions received", "Awaiting grading", "Active quizzes"):
        assert label in html
    assert "Quiz 3" in html and "Quiz 4" in html and "Amal Karunaratne" in html and "Needs grading" in html
    assert "<b>1</b><span>Awaiting grading" in html and "<b>1</b><span>Active quizzes" in html


def test_lecturer_dashboard_only_shows_own_courses(client, course, lecturer, make_user):
    other_lec = make_user("x", "lecturer")
    other = Course.objects.create(code="ZZ1", title="Secret", credits=3)
    other.lecturers.add(other_lec)
    Quiz.objects.create(course=other, title="Hidden quiz")
    html = login(client, lecturer).get(reverse("accounts:lecturer-dashboard")).content.decode()
    assert "Hidden quiz" not in html


def test_quiz_network_pill_follows_the_rules(client, course, lecturer):
    Quiz.objects.create(course=course, title="Quiz 3")
    page = reverse("accounts:lecturer-dashboard")
    assert "Campus network" not in login(client, lecturer).get(page).content.decode()
    AllowedNetwork.objects.create(name="Campus", cidr="10.0.0.0/8", scope="quiz")
    assert "Campus network" in client.get(page).content.decode()


def test_quiz_switch_goes_back_to_the_dashboard(client, course, lecturer):
    q = Quiz.objects.create(course=course, title="Quiz 3")
    login(client, lecturer)
    r = client.post(reverse("quizzes:action", args=[q.pk, "toggle-enabled"]), {"next": reverse("accounts:lecturer-dashboard")})
    assert r.status_code == 302 and r.url == reverse("accounts:lecturer-dashboard")
    q.refresh_from_db()
    assert q.is_enabled is False
    # only same-site paths are followed
    r = client.post(reverse("quizzes:action", args=[q.pk, "toggle-enabled"]), {"next": "https://evil.example/"})
    assert r.url == reverse("quizzes:editor", args=[q.pk])
    r = client.post(reverse("quizzes:action", args=[q.pk, "toggle-enabled"]))
    assert r.url == reverse("quizzes:editor", args=[q.pk])


def test_lecturer_with_no_courses(client, lecturer, db):
    html = login(client, lecturer).get(reverse("accounts:lecturer-dashboard")).content.decode()
    assert "You are not teaching any course yet." in html and "No quizzes" in html or "Quizzes for your courses" in html


# ---------------- admin ----------------

def test_admin_overview_shows_the_new_blocks(client, admin_user):
    AuditLog.objects.create(user=admin_user, action="sign_in", target="admin")
    AuditLog.objects.create(action="ip_blocked", target="/quizzes/1/")
    html = login(client, admin_user).get(reverse("accounts:admin-overview")).content.decode()
    for text in ("System overview", "Total users", "Active courses", "Online now", "Blocked attempts today", "Logins this week", "Server health", "Recent activity", "Last backup"):
        assert text in html
    assert "<b>1</b><span>Blocked attempts today" in html
    assert 'class="bars' in html and "Signed in" in html


def test_admin_overview_without_any_sign_ins(client, admin_user):
    html = login(client, admin_user).get(reverse("accounts:admin-overview")).content.decode()
    assert "No sign-ins in the last seven days." in html


def test_login_chart_counts_per_day(db, admin_user):
    from apps.administration import reports

    for _ in range(3):
        AuditLog.objects.create(user=admin_user, action="sign_in", target="admin")
    AuditLog.objects.create(user=admin_user, action="sign_out", target="admin")
    old = AuditLog.objects.create(user=admin_user, action="sign_in", target="admin")
    AuditLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=9))
    week, total = reports.logins_last_week()
    assert total == 3 and len(week) == 7 and week[-1]["count"] == 3 and week[-1]["pct"] == 100


def test_health_checks(db, settings, tmp_path):
    from apps.administration import reports

    settings.BACKUP_DIR = tmp_path / "backups"

    h = reports.health()
    assert h["database"] == ("Healthy", "ok") and h["backup"] is None
    assert 0 <= h["storage"] <= 100
    settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    assert reports.health()["email"][1] == "warn"
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    assert reports.health()["email"] == ("Configured", "ok")


# ---------------- search ----------------

def search(client, q, tab="all"):
    return client.get(reverse("accounts:search"), {"q": q, "tab": tab})


def test_search_needs_sign_in(client, db):
    assert search(client, "data").status_code == 302


def test_topbar_has_a_working_search_box(client, student):
    html = login(client, student).get(reverse("accounts:student-dashboard")).content.decode()
    assert 'action="/search/"' in html and 'name="q"' in html


def test_student_finds_courses_activities_forum_and_people(client, course, enrolled, lecturer):
    now = timezone.now()
    Quiz.objects.create(course=course, title="Normalisation quiz", closes_at=now + timedelta(days=3))
    Assignment.objects.create(course=course, title="Normalisation worksheet", due_at=now + timedelta(days=3))
    ForumTopic.objects.create(course=course, author=lecturer, title="Normalisation help")
    login(client, enrolled)
    html = search(client, "normalis").content.decode()
    assert "Normalisation quiz" in html and "Normalisation worksheet" in html and "Normalisation help" in html
    assert "3 results for" in html
    assert "Database Systems" in search(client, "database").content.decode()
    assert "Nimal Perera" in search(client, "perera", "people").content.decode()


def test_search_tabs_filter(client, course, enrolled, lecturer):
    Quiz.objects.create(course=course, title="Database quiz", closes_at=timezone.now() + timedelta(days=1))
    login(client, enrolled)
    only_people = search(client, "database", "people").content.decode()
    assert "Database quiz" not in only_people and "Nothing found" in only_people
    assert "Database quiz" in search(client, "database", "activities").content.decode()
    assert search(client, "database", "nonsense").status_code == 200


def test_search_never_leaks(client, course, enrolled, student, lecturer, make_user):
    Quiz.objects.create(course=course, title="Hidden quiz", is_visible=False)
    secret = Course.objects.create(code="ZZ9", title="Hidden Physics", is_visible=False)
    Enrolment.objects.create(course=secret, user=make_user("other", "student", first_name="Ghost"))
    login(client, enrolled)
    assert "Hidden quiz" not in search(client, "hidden").content.decode()
    assert "Hidden Physics" not in search(client, "physics").content.decode()
    assert "Ghost" not in search(client, "ghost").content.decode()  # shares no course
    assert "administrator" not in search(client, "admin").content.decode().lower().replace("search", "")


def test_lecturer_search_is_limited_to_own_courses(client, course, enrolled, lecturer, make_user):
    other = Course.objects.create(code="ZZ1", title="Other course", credits=3)
    Enrolment.objects.create(course=other, user=make_user("stranger", "student", first_name="Stranger"))
    login(client, lecturer)
    assert "Karunaratne" in search(client, "amal").content.decode()
    assert "Other course" not in search(client, "other").content.decode()
    assert "Stranger" not in search(client, "stranger").content.decode()


def test_admin_search_finds_users_by_email(client, admin_user, student):
    student.email = "amal@example.com"
    student.save()
    assert "Amal Karunaratne" in login(client, admin_user).get(reverse("accounts:search"), {"q": "amal@example"}).content.decode()


def test_search_input_is_handled_safely(client, student):
    login(client, student)
    assert "Type at least 2 characters." in search(client, "a").content.decode()
    r = search(client, "<script>alert(1)</script>" + "x" * 300)
    assert r.status_code == 200 and b"<script>alert(1)" not in r.content
    assert search(client, "").status_code == 200
    assert search(client, "%").status_code == 200


def test_private_files_are_searched_for_their_owner_only(client, student, make_user, db):
    from django.core.files.base import ContentFile

    from apps.files.models import PrivateFile

    f = PrivateFile(owner=student, size=3)
    f.file.save("er_diagram_draft.pdf", ContentFile(b"abc"))
    login(client, student)
    assert "er_diagram_draft" in search(client, "diagram", "materials").content.decode()
    other = make_user("other", "student")
    client.force_login(other)
    assert "er_diagram_draft" not in search(client, "diagram", "materials").content.decode()
