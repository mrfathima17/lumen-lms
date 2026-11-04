from datetime import date, datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.assignments.models import Assignment, Submission
from apps.courses.models import Enrolment
from apps.quizzes.models import Quiz
from apps.schedule import services
from apps.schedule.models import Event, TimetableSlot, TodoItem


def aware(d, t=time(10, 0)):
    return timezone.make_aware(datetime.combine(d, t), timezone.get_current_timezone())


@pytest.fixture
def day():
    return timezone.localdate() + timedelta(days=3)


# ---------- calendar items ----------

def test_deadlines_events_and_classes_appear_for_enrolled_student(course, enrolled, student, lecturer, day):
    Assignment.objects.create(course=course, title="A1", due_at=aware(day))
    Quiz.objects.create(course=course, title="Q1", closes_at=aware(day, time(15, 0)))
    Event.objects.create(owner=lecturer, course=course, title="Guest talk", starts_at=aware(day, time(9, 0)))
    Event.objects.create(owner=student, title="Gym", starts_at=aware(day, time(18, 0)))
    TimetableSlot.objects.create(course=course, weekday=day.weekday(), start_time=time(8), end_time=time(10), room="B1")
    items = services.calendar_items(student, day, day + timedelta(days=1))
    assert [(i["kind"], i["title"]) for i in items] == [("c", "CS201 Lecture"), ("e", "Guest talk"), ("a", "A1"), ("q", "Q1"), ("e", "Gym")]


def test_hidden_work_and_other_courses_and_others_personal_events_stay_out(course, enrolled, student, lecturer, make_user, day):
    from apps.courses.models import Course
    other = Course.objects.create(code="XX1", title="Other", credits=3)
    Assignment.objects.create(course=course, title="Hidden", due_at=aware(day), is_visible=False)
    Assignment.objects.create(course=other, title="Not mine", due_at=aware(day))
    Event.objects.create(owner=make_user("pal", "student"), title="Private", starts_at=aware(day))
    titles = [i["title"] for i in services.calendar_items(student, day, day + timedelta(days=1))]
    assert titles == []
    assert "Hidden" in [i["title"] for i in services.calendar_items(lecturer, day, day + timedelta(days=1))]  # staff see hidden work


def test_outside_range_excluded(course, enrolled, student, day):
    Assignment.objects.create(course=course, title="Later", due_at=aware(day + timedelta(days=40)))
    assert services.calendar_items(student, day, day + timedelta(days=7)) == []


def test_month_grid_shape(student):
    days = services.month_grid(student, 2026, 10)
    assert len(days) % 7 == 0 and days[0]["date"].weekday() == 0
    assert sum(1 for d in days if not d["off"]) == 31


# ---------- calendar views ----------

def test_calendar_page_and_bad_month_falls_back(client, course, enrolled, student, day):
    Assignment.objects.create(course=course, title="Essay due", due_at=aware(day))
    client.force_login(student)
    month = day.strftime("%Y-%m")
    assert b"Essay due" in client.get(reverse("schedule:calendar") + f"?month={month}").content
    for bad in ("garbage", "2026-13", "2026", ""):
        assert client.get(reverse("schedule:calendar") + f"?month={bad}").status_code == 200


def test_student_adds_personal_event_but_cannot_share_with_course(client, course, enrolled, student, day):
    client.force_login(student)
    url = reverse("schedule:event-new")
    assert b'name="course"' not in client.get(url).content
    r = client.post(url, {"title": "Study", "starts_at": f"{day}T09:00", "course": course.pk})
    ev = Event.objects.get()
    assert r.status_code == 302 and ev.course is None and ev.owner == student
    assert f"month={day:%Y-%m}" in r["Location"]


def test_lecturer_shares_event_with_course_students(client, course, enrolled, student, lecturer, day):
    client.force_login(lecturer)
    client.post(reverse("schedule:event-new"), {"title": "Exam briefing", "starts_at": f"{day}T09:00", "ends_at": f"{day}T10:00", "course": course.pk})
    assert Event.objects.get().course == course
    assert [i["title"] for i in services.calendar_items(student, day, day + timedelta(days=1))] == ["Exam briefing"]


def test_lecturer_cannot_share_with_course_they_do_not_teach(client, course, make_user, day):
    from apps.courses.models import Course
    other = Course.objects.create(code="XX1", title="Other", credits=3)
    client.force_login(make_user("lect2", "lecturer"))
    r = client.post(reverse("schedule:event-new"), {"title": "Sneaky", "starts_at": f"{day}T09:00", "course": other.pk})
    assert r.status_code == 200 and not Event.objects.exists()


def test_event_end_before_start_rejected(client, student, day):
    client.force_login(student)
    r = client.post(reverse("schedule:event-new"), {"title": "Odd", "starts_at": f"{day}T10:00", "ends_at": f"{day}T09:00"})
    assert r.status_code == 200 and b"after the start" in r.content and not Event.objects.exists()


def test_event_delete_permissions(client, course, enrolled, student, lecturer, make_user, day):
    mine = Event.objects.create(owner=student, title="Mine", starts_at=aware(day))
    shared = Event.objects.create(owner=lecturer, course=course, title="Shared", starts_at=aware(day))
    client.force_login(student)
    assert client.post(reverse("schedule:event-delete", args=[shared.pk])).status_code == 403  # a student cannot delete a lecturer's event
    client.force_login(make_user("lect2", "lecturer"))
    assert client.post(reverse("schedule:event-delete", args=[mine.pk])).status_code == 403
    assert client.post(reverse("schedule:event-delete", args=[shared.pk])).status_code == 403
    client.force_login(lecturer)
    assert client.get(reverse("schedule:event-delete", args=[shared.pk])).status_code == 405
    assert client.post(reverse("schedule:event-delete", args=[shared.pk])).status_code == 302
    client.force_login(student)
    assert client.post(reverse("schedule:event-delete", args=[mine.pk])).status_code == 302
    assert not Event.objects.exists()


# ---------- timetable ----------

def test_timetable_shows_only_own_courses(client, course, enrolled, student, make_user):
    from apps.courses.models import Course
    other = Course.objects.create(code="XX1", title="Other", credits=3)
    TimetableSlot.objects.create(course=course, weekday=2, start_time=time(14), end_time=time(16), room="Lab 2", kind="lab")
    TimetableSlot.objects.create(course=other, weekday=2, start_time=time(8), end_time=time(9))
    client.force_login(student)
    body = client.get(reverse("schedule:timetable")).content
    assert b"Wed" in body and b"Lab 2" in body and b"XX1" not in body


def test_lecturer_manages_slots(client, course, enrolled, student, lecturer, make_user):
    client.force_login(lecturer)
    url = reverse("schedule:course-timetable", args=[course.pk])
    assert client.post(url, {"kind": "lecture", "weekday": "0", "start_time": "09:00", "end_time": "11:00", "room": "A1"}).status_code == 302
    bad = client.post(url, {"kind": "lecture", "weekday": "0", "start_time": "11:00", "end_time": "09:00"})
    assert bad.status_code == 200 and TimetableSlot.objects.count() == 1
    slot = TimetableSlot.objects.get()
    for u in (student, make_user("intruder", "lecturer")):
        client.force_login(u)
        assert client.get(url).status_code == 403
        assert client.post(reverse("schedule:slot-delete", args=[slot.pk])).status_code == 403
    client.force_login(lecturer)
    assert client.post(reverse("schedule:slot-delete", args=[slot.pk])).status_code == 302
    assert not TimetableSlot.objects.exists()


# ---------- ics ----------

def test_ics_download_escapes_text(client, course, enrolled, student, day):
    Event.objects.create(owner=student, title="Bad,title;x\nEND:VEVENT\nBEGIN:VEVENT", starts_at=aware(day))
    client.force_login(student)
    r = client.get(reverse("schedule:export-ics"))
    text = r.content.decode()
    assert r["Content-Type"].startswith("text/calendar") and "attachment" in r["Content-Disposition"]
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.split("\r\n").count("BEGIN:VEVENT") == 1  # the injected line was neutralised
    assert r"Bad\,title\;x\nEND:VEVENT" in text


# ---------- to-do ----------

def test_todo_flow(client, student):
    client.force_login(student)
    assert client.post(reverse("schedule:todo-add"), {"title": "Read chapter 4", "due_date": "2026-10-30"}).status_code == 302
    t = TodoItem.objects.get()
    assert t.user == student and t.due_date == date(2026, 10, 30)
    client.post(reverse("schedule:todo-toggle", args=[t.pk]))
    t.refresh_from_db()
    assert t.done and t.done_at
    client.post(reverse("schedule:todo-toggle", args=[t.pk]))
    t.refresh_from_db()
    assert not t.done and t.done_at is None
    client.post(reverse("schedule:todo-delete", args=[t.pk]))
    assert not TodoItem.objects.exists()


def test_todo_validation_and_ownership(client, student, lecturer):
    client.force_login(student)
    client.post(reverse("schedule:todo-add"), {"title": "   "})
    client.post(reverse("schedule:todo-add"), {"title": "x" * 201})
    assert not TodoItem.objects.exists()
    t = TodoItem.objects.create(user=lecturer, title="Secret plan")
    assert client.post(reverse("schedule:todo-toggle", args=[t.pk])).status_code == 403
    assert client.post(reverse("schedule:todo-delete", args=[t.pk])).status_code == 403
    assert client.get(reverse("schedule:todo-toggle", args=[t.pk])).status_code == 405
    assert TodoItem.objects.filter(pk=t.pk, done=False).exists()
    assert b"Secret plan" not in client.get(reverse("schedule:todo")).content


def test_todo_page_shows_unsubmitted_deadlines_only(client, course, enrolled, student, day):
    a1 = Assignment.objects.create(course=course, title="Not done yet", due_at=aware(day))
    a2 = Assignment.objects.create(course=course, title="Already handed in", due_at=aware(day))
    Submission.objects.create(assignment=a2, student=student, submitted_at=timezone.now())
    TodoItem.objects.create(user=student, title="Old task", due_date=timezone.localdate() - timedelta(days=2))
    client.force_login(student)
    r = client.get(reverse("schedule:todo"))
    body = r.content.decode()
    assert "Not done yet" in body and "Already handed in" not in body and "Overdue" in body
    assert r.context["stats"]["overdue"] == 1 and r.context["stats"]["week"] == 1


def test_anonymous_redirected_and_nav_links(client, student, lecturer):
    for name in ("calendar", "timetable", "todo", "export-ics"):
        assert client.get(reverse(f"schedule:{name}")).status_code == 302
    client.force_login(student)
    page = client.get(reverse("accounts:student-dashboard")).content
    assert all(reverse(f"schedule:{n}").encode() in page for n in ("calendar", "timetable", "todo"))
    client.force_login(lecturer)
    page = client.get(reverse("accounts:lecturer-dashboard")).content
    assert reverse("schedule:calendar").encode() in page and reverse("schedule:timetable").encode() in page
