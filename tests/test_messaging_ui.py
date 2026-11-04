import pytest
from django.urls import reverse

from apps.courses.models import Enrolment
from apps.messaging import services
from apps.messaging.models import Announcement, ForumTopic, Notification


def login(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def thread(course, enrolled, lecturer):
    first = services.send_message(lecturer, enrolled, "Mid-term schedule", "The schedule is on the course page.")
    reply = services.send_message(enrolled, lecturer, "Re: Mid-term schedule", "Thank you!", parent=first)
    return first, reply


def test_inbox_is_two_pane_with_unread_dot(client, enrolled, thread):
    html = login(client, enrolled).get(reverse("messaging:inbox")).content.decode()
    assert 'class="card mail"' in html and "Select a message" in html
    assert "Mid-term schedule" in html and 'class="dot"' in html
    assert "has-chat" not in html


def test_detail_shows_bubbles_and_marks_read(client, enrolled, lecturer, thread):
    first, _ = thread
    html = login(client, enrolled).get(reverse("messaging:detail", args=[first.pk])).content.decode()
    assert "mail has-chat" in html and 'class="b me"' in html and 'class="b"' in html and "Send" in html
    assert "Thank you!" in html and "The schedule is on the course page." in html
    first.refresh_from_db()
    assert first.read_at is not None
    assert 'class="dot"' not in client.get(reverse("messaging:inbox")).content.decode()


def test_sent_box_lists_recipient(client, enrolled, lecturer, thread):
    html = login(client, enrolled).get(reverse("messaging:sent")).content.decode()
    assert "Nimal Perera" in html and "Re: Mid-term schedule" in html


def test_reply_from_the_composer_still_works(client, enrolled, lecturer, thread):
    first, _ = thread
    res = login(client, enrolled).post(reverse("messaging:reply", args=[first.pk]), {"body": "One more question"})
    assert res.status_code == 302
    assert "One more question" in client.get(res.url).content.decode()


def test_announcements_feed(client, course, enrolled, lecturer):
    Announcement.objects.create(course=course, author=lecturer, title="Lab 3 moved", body="Thursday 10 AM")
    Announcement.objects.create(course=None, author=lecturer, title="Library hours", body="Open late")
    html = login(client, enrolled).get(reverse("messaging:announcements")).content.decode()
    assert "Lab 3 moved" in html and "Course" in html and "University" in html and "ago" in html


def test_announcement_form_lists_recent_posts(client, course, lecturer):
    Announcement.objects.create(course=course, author=lecturer, title="Earlier news", body="x")
    html = login(client, lecturer).get(reverse("messaging:announcement-new")).content.decode()
    assert "Recently posted" in html and "Earlier news" in html and "New announcement" in html


def test_notifications_tabs_and_settings_link(client, enrolled):
    Notification.objects.create(user=enrolled, text="Your grade was released", kind="grade")
    html = login(client, enrolled).get(reverse("messaging:notifications")).content.decode()
    assert 'class="tabs"' in html and "Notification settings" in html and "1 unread" in html and "ago" in html
    assert "Your grade was released" in client.get(reverse("messaging:notifications") + "?filter=grade").content.decode()
    assert "Your grade was released" not in client.get(reverse("messaging:notifications") + "?filter=forum").content.decode()


def test_forum_topic_rows_and_post_avatars(client, course, enrolled, lecturer):
    t = services.create_topic(enrolled, course, "3NF vs BCNF", "What is the difference?")
    html = login(client, enrolled).get(reverse("messaging:forum", args=[course.pk])).content.decode()
    assert 'class="th on"' in html and "3NF vs BCNF" in html and "0 replies" in html and "What is the difference?" in html
    page = client.get(reverse("messaging:topic", args=[t.pk])).content.decode()
    assert 'class="post"' in page and "What is the difference?" in page
