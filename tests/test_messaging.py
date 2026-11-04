import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from apps.courses.models import Course, Enrolment
from apps.messaging import services
from apps.messaging.models import Announcement, ForumPost, ForumTopic, Message, Notification


@pytest.fixture
def classmate(make_user, course):
    u = make_user("s2026-0150", "student", first_name="Sara", last_name="Fernando")
    Enrolment.objects.create(course=course, user=u)
    return u


@pytest.fixture
def stranger(make_user):
    return make_user("stranger", "student", first_name="Una", last_name="Known")


@pytest.fixture
def other_course(db):
    return Course.objects.create(code="XX1", title="Other", credits=3)


# ---------- who can message whom ----------

def test_recipient_rules(course, enrolled, student, classmate, lecturer, stranger, admin_user, make_user):
    ok = set(services.allowed_recipients(student).values_list("username", flat=True))
    assert ok == {"s2026-0150", "nperera", "admin1"}  # classmate, own lecturer, administrator; not the stranger
    assert set(services.allowed_recipients(stranger).values_list("username", flat=True)) == {"admin1"}
    assert set(services.allowed_recipients(admin_user).values_list("username", flat=True)) == {"s2026-0142", "s2026-0150", "nperera", "stranger"}  # an administrator can reach everyone
    assert not services.can_message(student, student)
    lecturer2 = make_user("lect2", "lecturer")
    assert not services.can_message(student, lecturer2)  # teaches nothing the student is in


def test_disabled_and_suspended_people_cannot_be_messaged(course, enrolled, student, classmate, lecturer):
    classmate.is_active = False
    classmate.save()
    assert not services.can_message(student, classmate)
    Enrolment.objects.filter(user=student).update(status="suspended")
    assert not services.can_message(student, lecturer)


def test_send_message_refuses_strangers(student, stranger):
    with pytest.raises(PermissionDenied):
        services.send_message(student, stranger, "Hi", "Hello")
    assert not Message.objects.exists()


# ---------- message views ----------

def test_send_read_reply_flow(client, course, enrolled, student, lecturer):
    client.force_login(student)
    r = client.post(reverse("messaging:compose"), {"recipient": lecturer.pk, "subject": "Question", "body": "Is the deadline fixed?"})
    msg = Message.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("messaging:detail", args=[msg.pk])
    assert Notification.objects.get().user == lecturer and services.unread_messages(lecturer) == 1

    client.force_login(lecturer)
    assert b"Is the deadline fixed?" in client.get(reverse("messaging:detail", args=[msg.pk])).content
    assert services.unread_messages(lecturer) == 0
    client.post(reverse("messaging:reply", args=[msg.pk]), {"body": "Yes, Friday."})
    reply = Message.objects.get(parent=msg)
    assert reply.recipient == student and reply.subject == "Re: Question"
    client.post(reverse("messaging:reply", args=[reply.pk]), {"body": "ok"})
    assert Message.objects.order_by("-pk").first().subject == "Re: Question"  # no "Re: Re:"

    client.force_login(student)
    page = client.get(reverse("messaging:detail", args=[reply.pk])).content
    assert b"Is the deadline fixed?" in page and b"Yes, Friday." in page  # whole conversation shown


def test_messages_are_private(client, course, enrolled, student, classmate, lecturer, stranger):
    msg = services.send_message(student, lecturer, "Private", "secret words")
    for u in (classmate, stranger):
        client.force_login(u)
        assert client.get(reverse("messaging:detail", args=[msg.pk])).status_code == 403
        assert client.post(reverse("messaging:reply", args=[msg.pk]), {"body": "x"}).status_code == 403
        assert client.post(reverse("messaging:delete", args=[msg.pk])).status_code == 403
        assert b"secret words" not in client.get(reverse("messaging:inbox")).content


def test_delete_hides_for_one_side_only(client, course, enrolled, student, lecturer):
    msg = services.send_message(student, lecturer, "Hi", "Body")
    client.force_login(lecturer)
    assert client.get(reverse("messaging:delete", args=[msg.pk])).status_code == 405
    client.post(reverse("messaging:delete", args=[msg.pk]))
    assert client.get(reverse("messaging:detail", args=[msg.pk])).status_code == 403
    client.force_login(student)
    assert client.get(reverse("messaging:detail", args=[msg.pk])).status_code == 200
    client.post(reverse("messaging:delete", args=[msg.pk]))
    assert not Message.objects.exists()  # gone once both sides deleted


def test_compose_validation_and_prefill(client, course, enrolled, student, lecturer, stranger):
    client.force_login(student)
    url = reverse("messaging:compose")
    assert client.post(url, {"recipient": stranger.pk, "subject": "x", "body": "y"}).status_code == 200  # not in the allowed list
    assert client.post(url, {"recipient": lecturer.pk, "subject": "", "body": "y"}).status_code == 200
    assert client.post(url, {"recipient": lecturer.pk, "subject": "x", "body": "y" * 5001}).status_code == 200
    assert not Message.objects.exists()
    assert f'value="{lecturer.pk}" selected'.encode() in client.get(url + f"?to={lecturer.pk}").content


def test_html_in_messages_is_escaped(client, course, enrolled, student, lecturer):
    msg = services.send_message(student, lecturer, "<b>hi</b>", "<script>alert(1)</script>")
    client.force_login(lecturer)
    body = client.get(reverse("messaging:detail", args=[msg.pk])).content
    assert b"<script>alert(1)" not in body and b"&lt;script&gt;" in body


def test_inbox_and_sent_lists(client, course, enrolled, student, lecturer):
    services.send_message(student, lecturer, "Hello lecturer", "x")
    client.force_login(lecturer)
    assert b"Hello lecturer" in client.get(reverse("messaging:inbox")).content
    assert b"Hello lecturer" not in client.get(reverse("messaging:sent")).content
    client.force_login(student)
    assert b"Hello lecturer" in client.get(reverse("messaging:sent")).content


# ---------- forums ----------

def test_forum_access_follows_course_membership(client, course, enrolled, student, stranger, lecturer, make_user):
    t = services.create_topic(student, course, "Help with joins", "How do I join?")
    for u in (stranger, make_user("lect2", "lecturer")):
        client.force_login(u)
        assert client.get(reverse("messaging:forum", args=[course.pk])).status_code == 403
        assert client.get(reverse("messaging:topic", args=[t.pk])).status_code == 403
        assert client.post(reverse("messaging:topic", args=[t.pk]), {"body": "hi"}).status_code == 403
        assert client.post(reverse("messaging:topic-new", args=[course.pk]), {"title": "x", "body": "y"}).status_code == 403
    assert ForumPost.objects.count() == 1


def test_topic_reply_and_notifications(client, course, enrolled, student, classmate, lecturer):
    client.force_login(student)
    client.post(reverse("messaging:topic-new", args=[course.pk]), {"title": "Joins", "body": "Question"})
    t = ForumTopic.objects.get()
    assert Notification.objects.filter(user=lecturer, kind="forum").count() == 1 and not Notification.objects.filter(user=student).exists()
    client.force_login(lecturer)
    client.post(reverse("messaging:topic", args=[t.pk]), {"body": "Use INNER JOIN."})
    assert Notification.objects.filter(user=student, kind="forum").count() == 1
    assert t.posts.count() == 2
    ForumTopic.objects.get(pk=t.pk).last_post_at  # updated on reply
    client.force_login(classmate)
    assert b"Use INNER JOIN." in client.get(reverse("messaging:topic", args=[t.pk])).content


def test_locked_topic_blocks_students_not_lecturers(client, course, enrolled, student, lecturer):
    t = services.create_topic(lecturer, course, "Rules", "Read these")
    client.force_login(student)
    assert client.post(reverse("messaging:topic-flag", args=[t.pk, "locked"])).status_code == 403
    client.force_login(lecturer)
    client.post(reverse("messaging:topic-flag", args=[t.pk, "locked"]))
    client.post(reverse("messaging:topic-flag", args=[t.pk, "pinned"]))
    t.refresh_from_db()
    assert t.locked and t.pinned
    assert client.post(reverse("messaging:topic-flag", args=[t.pk, "title"])).status_code == 403  # only known flags
    client.force_login(student)
    assert client.post(reverse("messaging:topic", args=[t.pk]), {"body": "late reply"}).status_code == 403
    assert t.posts.count() == 1
    client.force_login(lecturer)
    client.post(reverse("messaging:topic", args=[t.pk]), {"body": "Clarification"})
    assert t.posts.count() == 2


def test_post_and_topic_deletion_rights(client, course, enrolled, student, classmate, lecturer):
    t = services.create_topic(student, course, "T", "first")
    mine = services.reply(student, t, "mine")
    theirs = services.reply(classmate, t, "theirs")
    client.force_login(classmate)
    assert client.post(reverse("messaging:post-delete", args=[mine.pk])).status_code == 403
    assert client.post(reverse("messaging:topic-delete", args=[t.pk])).status_code == 403
    client.force_login(student)
    client.post(reverse("messaging:post-delete", args=[mine.pk]))
    first = t.posts.first()
    client.post(reverse("messaging:post-delete", args=[first.pk]))  # first post cannot be removed alone
    assert set(t.posts.values_list("body", flat=True)) == {"first", "theirs"}
    client.force_login(lecturer)
    client.post(reverse("messaging:post-delete", args=[theirs.pk]))
    client.post(reverse("messaging:topic-delete", args=[t.pk]))
    assert not ForumTopic.objects.exists()


def test_forums_index_lists_own_courses_only(client, course, enrolled, student, other_course):
    client.force_login(student)
    body = client.get(reverse("messaging:forums")).content
    assert b"CS201" in body and b"XX1" not in body


# ---------- announcements ----------

def test_course_announcement_reaches_enrolled_students_only(client, course, enrolled, student, lecturer, stranger, other_course):
    client.force_login(lecturer)
    r = client.post(reverse("messaging:announcement-new"), {"course": course.pk, "title": "Class moved", "body": "Room B2"})
    assert r.status_code == 302 and Announcement.objects.get().course == course
    assert set(Notification.objects.values_list("user__username", flat=True)) == {student.username}
    client.force_login(student)
    assert b"Class moved" in client.get(reverse("messaging:announcements")).content
    client.force_login(stranger)
    assert b"Class moved" not in client.get(reverse("messaging:announcements")).content


def test_announcement_permissions(client, course, enrolled, student, lecturer, make_user, admin_user):
    client.force_login(student)
    assert client.get(reverse("messaging:announcement-new")).status_code == 403
    client.force_login(make_user("lect2", "lecturer"))
    r = client.post(reverse("messaging:announcement-new"), {"course": course.pk, "title": "x", "body": "y"})
    assert r.status_code == 200 and not Announcement.objects.exists()  # not their course
    r = client.post(reverse("messaging:announcement-new"), {"course": "", "title": "x", "body": "y"})
    assert r.status_code == 200 and not Announcement.objects.exists()  # lecturers cannot announce site-wide
    with pytest.raises(PermissionDenied):
        services.announce(lecturer, None, "x", "y")


def test_site_wide_announcement_by_admin(client, course, enrolled, student, stranger, admin_user):
    client.force_login(admin_user)
    client.post(reverse("messaging:announcement-new"), {"course": "", "title": "Holiday", "body": "Closed Monday"})
    a = Announcement.objects.get()
    assert a.course is None
    assert set(Notification.objects.values_list("user__username", flat=True)) == {"s2026-0142", "stranger", "nperera"}  # everyone but the author
    client.force_login(stranger)
    assert b"Holiday" in client.get(reverse("messaging:announcements")).content


def test_announcement_delete_rights(client, course, enrolled, student, lecturer, admin_user, make_user):
    a = services.announce(lecturer, course, "T", "B")
    client.force_login(student)
    assert client.post(reverse("messaging:announcement-delete", args=[a.pk])).status_code == 403
    client.force_login(make_user("lect2", "lecturer"))
    assert client.post(reverse("messaging:announcement-delete", args=[a.pk])).status_code == 403
    client.force_login(admin_user)
    assert client.post(reverse("messaging:announcement-delete", args=[a.pk])).status_code == 302
    assert not Announcement.objects.exists()


# ---------- notifications ----------

def test_notification_open_marks_read_and_redirects(client, student):
    n = Notification.objects.create(user=student, text="Hello", url="/forums/", kind="forum")
    client.force_login(student)
    r = client.get(reverse("messaging:open", args=[n.pk]))
    assert r.status_code == 302 and r["Location"] == "/forums/"
    n.refresh_from_db()
    assert n.read_at is not None


@pytest.mark.parametrize("url", ["https://evil.example/x", "//evil.example/x", "javascript:alert(1)", "/\\evil.example"])
def test_notification_never_redirects_off_site(client, student, url):
    n = Notification.objects.create(user=student, text="x", url=url)
    client.force_login(student)
    assert client.get(reverse("messaging:open", args=[n.pk]))["Location"] == reverse("messaging:notifications")


def test_notifications_are_per_user_and_filterable(client, student, lecturer):
    Notification.objects.create(user=student, text="for student", kind="message")
    Notification.objects.create(user=student, text="read one", kind="forum", read_at="2026-01-01T00:00:00Z")
    other = Notification.objects.create(user=lecturer, text="for lecturer")
    client.force_login(student)
    assert client.get(reverse("messaging:open", args=[other.pk])).status_code == 404
    body = client.get(reverse("messaging:notifications")).content
    assert b"for student" in body and b"for lecturer" not in body
    assert b"read one" not in client.get(reverse("messaging:notifications") + "?filter=unread").content
    assert b"for student" not in client.get(reverse("messaging:notifications") + "?filter=forum").content
    client.post(reverse("messaging:read-all"))
    assert services.unread_notifications(student) == 0 and services.unread_notifications(lecturer) == 1


def test_grading_events_notify_the_student(course, enrolled, student, lecturer):
    from datetime import timedelta
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone
    from apps.assignments import services as asg
    from apps.assignments.models import Assignment
    from apps.grading import services as gs
    from apps.grading.models import GradeItem

    a = Assignment.objects.create(course=course, title="A1", due_at=timezone.now() + timedelta(days=1))
    sub = asg.submit(a, student, SimpleUploadedFile("a.pdf", b"x"))
    asg.grade(sub, 70, "", lecturer)
    GradeItem.objects.create(course=course, title="A1", kind="assignment", assignment=a, weight=100)
    gs.publish_results(course, lecturer)
    texts = list(Notification.objects.filter(user=student, kind="grade").values_list("text", flat=True))
    assert any("A1 has been graded" in t for t in texts) and any("result has been published" in t for t in texts)


def test_topbar_badges_and_nav_links(client, student, lecturer, course, enrolled):
    services.send_message(lecturer, student, "Hi", "x")
    client.force_login(student)
    page = client.get(reverse("accounts:student-dashboard")).content
    assert b"1 unread" in page
    for name in ("inbox", "forums", "announcements", "notifications"):
        assert reverse(f"messaging:{name}").encode() in page


def test_anonymous_redirected(client, db):
    for name in ("inbox", "forums", "announcements", "notifications", "compose"):
        assert client.get(reverse(f"messaging:{name}")).status_code == 302


def test_announcement_draft_pin_priority_and_edit(client, course, enrolled, student, lecturer):
    from apps.messaging.models import Announcement, Notification
    client.force_login(lecturer)
    client.post(reverse("messaging:announcement-new"), {"course": course.pk, "title": "Soon", "body": "b", "priority": "urgent", "pinned": "on", "draft": "1"})
    a = Announcement.objects.get(title="Soon")
    assert a.is_draft and a.pinned and a.priority == "urgent"
    assert not Notification.objects.filter(user=student).exists()
    client.force_login(student)
    assert b"Soon" not in client.get(reverse("messaging:announcements")).content
    client.force_login(lecturer)
    assert b"Draft" in client.get(reverse("messaging:announcements")).content
    r = client.post(reverse("messaging:announcement-edit", args=[a.pk]), {"title": "Soon", "body": "b2", "priority": "urgent", "pinned": "on"})
    assert r.status_code == 302
    a.refresh_from_db()
    assert not a.is_draft and a.body == "b2"
    assert Notification.objects.filter(user=student, text__startswith="Urgent announcement").exists()
    client.force_login(student)
    assert b"Soon" in client.get(reverse("messaging:announcements")).content
    assert client.get(reverse("messaging:announcement-edit", args=[a.pk])).status_code == 403
