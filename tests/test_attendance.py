from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.attendance import services
from apps.attendance.models import AttendanceRecord, AttendanceSession
from apps.core.models import SiteSettings
from apps.courses.models import Enrolment

D = Decimal


@pytest.fixture
def session(course, lecturer):
    return AttendanceSession.objects.create(course=course, title="Lecture 1", held_on=date(2026, 10, 19), created_by=lecturer)


def mark(course, student, statuses):
    """Create one session per status and record the student against it."""
    for i, st in enumerate(statuses):
        s = AttendanceSession.objects.create(course=course, title=f"L{i}", held_on=date(2026, 9, 1 + i))
        AttendanceRecord.objects.create(session=s, student=student, status=st)


# ---------- rules ----------

def test_stats_present_and_late_attend_excused_ignored():
    st = services.stats(["present", "late", "absent", "excused", "present"])
    assert (st["attended"], st["counted"], st["excused"]) == (3, 4, 1)
    assert st["percent"] == D("75.0")


def test_stats_empty_has_no_percent():
    assert services.stats([])["percent"] is None
    assert services.stats(["excused"])["percent"] is None


def test_level_uses_site_threshold(db):
    assert services.level(D("79.9")) == "bad"
    assert services.level(D("80")) == "warn"
    assert services.level(D("85")) == "ok"
    assert services.level(None) == "mute"
    s = SiteSettings.load(); s.attendance_warning_percent = 90; s.save()
    assert services.level(D("85")) == "bad"


def test_sessions_needed_to_recover():
    st = services.stats(["present"] * 7 + ["absent"] * 3)  # 7/10 = 70%
    assert services.sessions_needed(st, 80) == 5  # (80*10 - 100*7) / 20 = 5
    assert services.sessions_needed(services.stats(["present"] * 9 + ["absent"]), 80) == 0
    assert services.sessions_needed(services.stats([]), 80) == 0


def test_student_stats_per_course(course, enrolled, student):
    mark(course, student, ["present", "absent", "late", "present"])
    assert services.student_course_stats(course, student)["percent"] == D("75.0")


# ---------- saving a sheet ----------

def test_save_sheet_creates_and_updates(course, enrolled, student, session):
    assert services.save_sheet(session, {student.pk: "absent"}) == 1
    services.save_sheet(session, {student.pk: "late"})
    assert AttendanceRecord.objects.get().status == "late"


def test_save_sheet_rejects_bad_status_and_strangers_atomically(course, enrolled, student, session, make_user):
    stranger = make_user("outsider", "student")
    with pytest.raises(ValueError):
        services.save_sheet(session, {student.pk: "present", stranger.pk: "present"})
    with pytest.raises(ValueError):
        services.save_sheet(session, {student.pk: "teleported"})
    assert not AttendanceRecord.objects.exists()


def test_suspended_students_are_not_on_the_sheet(course, enrolled, student, session):
    Enrolment.objects.filter(user=student).update(status="suspended")
    assert services.active_students(course) == []
    with pytest.raises(ValueError):
        services.save_sheet(session, {student.pk: "present"})


# ---------- lecturer views ----------

def test_create_session_then_sheet_flow(client, course, enrolled, student, lecturer):
    client.force_login(lecturer)
    r = client.post(reverse("attendance:session-new", args=[course.pk]), {"title": "Lab 1", "held_on": "2026-10-20", "start_time": "14:00"})
    s = AttendanceSession.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("attendance:sheet", args=[s.pk]) and s.created_by == lecturer
    page = client.get(reverse("attendance:sheet", args=[s.pk])).content
    assert b"has not been saved" in page and b'name="status_%d"' % student.pk in page
    assert client.post(reverse("attendance:sheet", args=[s.pk]), {f"status_{student.pk}": "late"}).status_code == 302
    assert AttendanceRecord.objects.get().status == "late"
    assert b"has not been saved" not in client.get(reverse("attendance:sheet", args=[s.pk])).content


def test_tampered_sheet_saves_nothing_and_shows_error(client, course, enrolled, student, lecturer, session):
    client.force_login(lecturer)
    r = client.post(reverse("attendance:sheet", args=[session.pk]), {f"status_{student.pk}": "nonsense"})
    assert r.status_code == 200 and b"Unknown attendance status" in r.content and not AttendanceRecord.objects.exists()


def test_session_form_validation(client, course, lecturer):
    client.force_login(lecturer)
    r = client.post(reverse("attendance:session-new", args=[course.pk]), {"title": "", "held_on": "not a date"})
    assert r.status_code == 200 and not AttendanceSession.objects.exists()


def test_course_page_lists_students_and_flags_low(client, course, enrolled, student, lecturer, session):
    mark(course, student, ["present", "absent", "absent", "present"])
    client.force_login(lecturer)
    body = client.get(reverse("attendance:course", args=[course.pk])).content
    assert b"50" in body and b"pill bad" in body and b"Lecture 1" in body


def test_delete_session_removes_records(client, course, enrolled, student, lecturer, session):
    AttendanceRecord.objects.create(session=session, student=student)
    client.force_login(lecturer)
    assert client.get(reverse("attendance:session-delete", args=[session.pk])).status_code == 405
    assert client.post(reverse("attendance:session-delete", args=[session.pk])).status_code == 302
    assert not AttendanceSession.objects.exists() and not AttendanceRecord.objects.exists()


def test_csv_export_and_formula_guard(client, course, enrolled, student, lecturer):
    student.first_name = "=SUM(1)"; student.save()
    s = AttendanceSession.objects.create(course=course, title="=EVIL", held_on=date(2026, 10, 1))
    AttendanceRecord.objects.create(session=s, student=student, status="present")
    client.force_login(lecturer)
    r = client.get(reverse("attendance:export", args=[course.pk]))
    text = r.content.decode()
    assert r["Content-Type"].startswith("text/csv") and "'=EVIL" in text and "'=SUM" in text and "100.0" in text
    assert ",=" not in text and "\n=" not in text


# ---------- permissions ----------

def test_only_the_course_lecturer_and_admin_can_manage(client, course, enrolled, student, make_user, admin_user, session):
    urls = [reverse("attendance:course", args=[course.pk]), reverse("attendance:session-new", args=[course.pk]),
            reverse("attendance:export", args=[course.pk]), reverse("attendance:sheet", args=[session.pk])]
    for u in (student, make_user("intruder", "lecturer")):
        client.force_login(u)
        for url in urls:
            assert client.get(url).status_code == 403
        assert client.post(reverse("attendance:sheet", args=[session.pk]), {}).status_code == 403
        assert client.post(reverse("attendance:session-delete", args=[session.pk])).status_code == 403
    client.force_login(student)
    assert client.get(reverse("attendance:course-list")).status_code == 403
    client.force_login(admin_user)
    assert all(client.get(url).status_code == 200 for url in urls)
    client.force_login(make_user("lect3", "lecturer"))
    assert client.get(reverse("attendance:my-attendance")).status_code == 403


def test_anonymous_redirected(client, course):
    assert client.get(reverse("attendance:course", args=[course.pk])).status_code == 302
    assert client.get(reverse("attendance:my-attendance")).status_code == 302


# ---------- student view ----------

def test_student_report_warns_when_below_threshold(client, course, enrolled, student):
    mark(course, student, ["present"] * 7 + ["absent"] * 3)
    client.force_login(student)
    body = client.get(reverse("attendance:my-attendance")).content.decode()
    assert "70" in body and "Below the 80% required" in body and "next 5 sessions" in body


def test_student_sees_only_own_records_and_filter(client, course, enrolled, student, make_user):
    other = make_user("other", "student")
    Enrolment.objects.create(course=course, user=other)
    mark(course, student, ["present"])
    mark(course, other, ["absent", "absent"])
    client.force_login(student)
    r = client.get(reverse("attendance:my-attendance"))
    assert len(r.context["recent"]) == 1 and r.context["overall"]["counted"] == 1
    assert len(client.get(reverse("attendance:my-attendance") + "?course=999").context["recent"]) == 0
    assert client.get(reverse("attendance:my-attendance") + "?course=abc").status_code == 200


def test_student_not_enrolled_sees_nothing(client, make_user, course, session):
    s = make_user("newbie", "student")
    client.force_login(s)
    r = client.get(reverse("attendance:my-attendance"))
    assert b"No courses" in r.content


def test_nav_links(client, enrolled, student, lecturer):
    client.force_login(student)
    assert reverse("attendance:my-attendance").encode() in client.get(reverse("accounts:student-dashboard")).content
    client.force_login(lecturer)
    assert reverse("attendance:course-list").encode() in client.get(reverse("accounts:lecturer-dashboard")).content


def test_sheet_loads_alpine_for_search_and_mark_all(client, course, enrolled, lecturer, session):
    client.force_login(lecturer)
    assert b"js/alpine.min.js" in client.get(reverse("attendance:sheet", args=[session.pk])).content
