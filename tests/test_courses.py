import pytest
from django.urls import reverse

from apps.courses.models import Course, Enrolment, Group, Topic
from apps.courses.services import enrol_students, parse_identifiers


def url(name, *args):
    return reverse(f"courses:{name}", args=args)


# ---- services ----

def test_parse_identifiers_dedupes_and_splits():
    assert parse_identifiers("a1, b2\nA1;  c3 ,,") == ["a1", "b2", "c3"]
    assert parse_identifiers("") == []


def test_enrol_students_reports_each_case(course, student, lecturer, make_user):
    make_user("s2", "student", index_number="IDX-2")
    res = enrol_students(course, [student.username, "idx-2", "ghost", lecturer.username, student.username])
    assert res["enrolled"] == [student.username, "idx-2"]
    assert res["not_found"] == ["ghost"] and res["not_student"] == [lecturer.username]
    assert res["already"] == [student.username]
    assert Enrolment.objects.filter(course=course).count() == 2


# ---- viewing ----

def test_student_sees_only_enrolled_courses(client, course, student, enrolled):
    other = Course.objects.create(code="CS999", title="Other")
    client.force_login(student)
    body = client.get(url("my-courses")).content
    assert b"CS201" not in body or b"Database Systems" in body
    assert b"Database Systems" in body and b"Other" not in body
    assert client.get(url("detail", course.pk)).status_code == 200
    assert client.get(url("detail", other.pk)).status_code == 403


def test_hidden_course_blocked_for_student_but_not_staff(client, course, enrolled, student, lecturer):
    course.is_visible = False
    course.save()
    client.force_login(student)
    assert client.get(url("detail", course.pk)).status_code == 403
    client.force_login(lecturer)
    assert client.get(url("detail", course.pk)).status_code == 200


def test_suspended_student_loses_access(client, course, enrolled, student):
    Enrolment.objects.filter(course=course, user=student).update(status="suspended")
    client.force_login(student)
    assert client.get(url("detail", course.pk)).status_code == 403


def test_lecturer_sees_only_own_courses(client, course, lecturer, make_user):
    other_lect = make_user("other", "lecturer")
    mine = client.force_login(lecturer) or client.get(url("my-courses")).content
    assert b"Database Systems" in mine
    client.force_login(other_lect)
    assert b"Database Systems" not in client.get(url("my-courses")).content
    assert client.get(url("detail", course.pk)).status_code == 403


def test_hidden_topics_not_shown_to_students(client, course, enrolled, student):
    Topic.objects.create(course=course, title="Visible one", position=0)
    Topic.objects.create(course=course, title="Secret one", position=1, is_visible=False)
    client.force_login(student)
    body = client.get(url("detail", course.pk)).content
    assert b"Visible one" in body and b"Secret one" not in body


# ---- catalog and self-enrolment ----

def test_catalog_search_and_self_enrol_rules(client, course, student):
    client.force_login(student)
    assert b"Enrolment by your lecturer" in client.get(url("catalog")).content
    assert client.post(url("self-enrol", course.pk)).status_code == 403  # not allowed

    course.allow_self_enrol = True
    course.enrol_key = "secret"
    course.save()
    r = client.post(url("self-enrol", course.pk), {"key": "wrong"})
    assert r.status_code == 302 and not Enrolment.objects.filter(course=course, user=student).exists()
    r = client.post(url("self-enrol", course.pk), {"key": "secret"})
    assert Enrolment.objects.filter(course=course, user=student).exists()
    assert client.get(url("catalog") + "?q=nomatch").content.count(b"Database Systems") == 0


def test_only_students_use_catalog(client, lecturer):
    client.force_login(lecturer)
    assert client.get(url("catalog")).status_code == 403


# ---- staff management ----

def test_lecturer_bulk_enrols_and_removes(client, course, lecturer, student):
    client.force_login(lecturer)
    client.post(url("bulk-enrol", course.pk), {"identifiers": student.username})
    e = Enrolment.objects.get(course=course, user=student)
    client.post(url("enrolment-action", course.pk, e.pk, "suspend"))
    e.refresh_from_db()
    assert e.status == "suspended"
    client.post(url("enrolment-action", course.pk, e.pk, "remove"))
    assert not Enrolment.objects.filter(pk=e.pk).exists()


def test_student_cannot_manage(client, course, enrolled, student):
    client.force_login(student)
    assert client.post(url("topic-add", course.pk), {"title": "x"}).status_code == 403
    assert client.post(url("bulk-enrol", course.pk), {"identifiers": "x"}).status_code == 403
    assert client.get(url("groups", course.pk)).status_code == 403


def test_other_lecturer_cannot_manage(client, course, make_user):
    client.force_login(make_user("intruder", "lecturer"))
    assert client.post(url("topic-add", course.pk), {"title": "x"}).status_code == 403


def test_topic_add_order_toggle_delete(client, course, lecturer):
    client.force_login(lecturer)
    for t in ("A", "B", "C"):
        client.post(url("topic-add", course.pk), {"title": t})
    titles = lambda: list(course.topics.values_list("title", flat=True))
    assert titles() == ["A", "B", "C"]
    b = course.topics.get(title="B")
    client.post(url("topic-action", course.pk, b.pk, "up"))
    assert titles() == ["B", "A", "C"]
    client.post(url("topic-action", course.pk, b.pk, "toggle"))
    b.refresh_from_db()
    assert not b.is_visible
    client.post(url("topic-action", course.pk, b.pk, "delete"))
    assert titles() == ["A", "C"]
    assert client.post(url("topic-action", course.pk, b.pk, "toggle")).status_code == 404


def test_unknown_action_is_refused(client, course, lecturer):
    client.force_login(lecturer)
    t = Topic.objects.create(course=course, title="T")
    assert client.post(url("topic-action", course.pk, t.pk, "explode")).status_code == 403


def test_topic_requires_title(client, course, lecturer):
    client.force_login(lecturer)
    client.post(url("topic-add", course.pk), {"title": ""})
    assert course.topics.count() == 0


def test_groups_only_accept_enrolled_students(client, course, lecturer, enrolled, student, make_user):
    outsider = make_user("outsider", "student")
    client.force_login(lecturer)
    client.post(url("groups", course.pk), {"name": "Lab A"})
    client.post(url("groups", course.pk), {"name": "lab a"})  # duplicate, case-insensitive
    assert Group.objects.filter(course=course).count() == 1
    g = Group.objects.get(course=course)
    client.post(url("group-member", course.pk, g.pk, "add"), {"user": student.pk})
    client.post(url("group-member", course.pk, g.pk, "add"), {"user": outsider.pk})
    assert list(g.members.all()) == [student]
    client.post(url("group-member", course.pk, g.pk, "remove"), {"user": student.pk})
    assert g.members.count() == 0


def test_get_on_post_only_endpoints(client, course, lecturer):
    client.force_login(lecturer)
    assert client.get(url("topic-add", course.pk)).status_code == 405
    assert client.get(url("bulk-enrol", course.pk)).status_code == 405


# ---- admin ----

def test_admin_course_crud_and_role_gate(client, admin_user, student, lecturer):
    client.force_login(student)
    assert client.get(url("admin-courses")).status_code == 403
    client.force_login(lecturer)
    assert client.get(url("admin-course-new")).status_code == 403
    client.force_login(admin_user)
    r = client.post(url("admin-course-new"), {"code": " it101 ", "title": "Intro", "credits": 3, "is_visible": "on"})
    assert r.status_code == 302
    c = Course.objects.get(code="IT101")
    client.post(url("admin-course-edit", c.pk), {"code": "IT101", "title": "Intro to IT", "credits": 3, "lecturers": [lecturer.pk]})
    c.refresh_from_db()
    assert c.title == "Intro to IT" and list(c.lecturers.all()) == [lecturer]
    assert b"Intro to IT" in client.get(url("admin-courses") + "?q=IT1").content


def test_admin_course_validation(client, admin_user, course):
    client.force_login(admin_user)
    r = client.post(url("admin-course-new"), {"code": "cs201", "title": "Dup", "credits": 3})
    assert r.status_code == 200 and Course.objects.filter(code="CS201").count() == 1
    r = client.post(url("admin-course-new"), {"code": "X1", "title": "Big", "credits": 99})
    assert r.status_code == 200 and not Course.objects.filter(code="X1").exists()


def test_admin_categories(client, admin_user):
    client.force_login(admin_user)
    client.post(url("admin-categories"), {"name": "Physics", "kind": "department"})
    assert b"Physics" in client.get(url("admin-categories")).content


def test_admin_course_area_respects_network_rule(client, admin_user, db):
    from apps.core.models import AllowedNetwork

    AllowedNetwork.objects.create(name="Office", cidr="203.0.113.0/24", scope="admin")
    client.force_login(admin_user)
    assert client.get(url("admin-courses"), REMOTE_ADDR="8.8.8.8").status_code == 403
    assert client.get(url("admin-courses"), REMOTE_ADDR="203.0.113.5").status_code == 200


def test_sidebar_highlights_my_courses_on_detail(client, course, lecturer):
    client.force_login(lecturer)
    body = client.get(url("detail", course.pk)).content.decode()
    assert 'href="/courses/" class="active"' in body


def test_student_count_counts_whole_class(client, course, enrolled, student, make_user):
    Enrolment.objects.create(course=course, user=make_user("s9", "student"))
    client.force_login(student)
    assert b"2 students" in client.get(url("my-courses")).content


def test_course_form_lists_lecturers_as_checkboxes(client, admin_user, lecturer, db):
    client.force_login(admin_user)
    body = client.get(url("admin-course-new")).content.decode()
    assert 'name="lecturers"' in body and 'type="checkbox"' in body and lecturer.username in body
