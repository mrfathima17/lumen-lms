"""Messaging rules.

Who may message whom: people who share a course (classmates and their lecturers), and everyone may reach an administrator.
Administrators may message anyone. Nobody can message a disabled account or themselves.
"""
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.courses import permissions as perm
from apps.courses.models import Course, Enrolment

from .models import Announcement, ForumPost, ForumTopic, Message, Notification


# ---------- notifications ----------

def notify(users, text, url="", kind="info"):
    """One notification per distinct active user. Never raises for a missing user."""
    seen, rows = set(), []
    for u in users:
        if u is None or u.pk in seen or not u.is_active:
            continue
        seen.add(u.pk)
        rows.append(Notification(user=u, text=text[:250], url=url[:250], kind=kind))
    Notification.objects.bulk_create(rows)
    if rows:
        from django.db import transaction

        from apps.core.jobs import dispatch

        from .tasks import email_notifications

        ids = [r.user_id for r in rows]
        transaction.on_commit(lambda: dispatch(email_notifications, ids, text[:250], url[:250]))
    return len(rows)


def unread_notifications(user):
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def safe_next(url):
    """Only same-site paths are followed from a stored notification."""
    return url if url.startswith("/") and not url.startswith("//") and "\\" not in url else ""


# ---------- direct messages ----------

def allowed_recipients(user):
    base = User.objects.filter(is_active=True).exclude(pk=user.pk)
    if user.role == "admin":
        return base
    ids = list(perm.visible_courses_for(user).values_list("pk", flat=True))
    return base.filter(
        Q(role="admin")
        | Q(enrolments__course_id__in=ids, enrolments__status=Enrolment.Status.ACTIVE)
        | Q(teaching_courses__pk__in=ids)
    ).distinct()


def can_message(sender, recipient):
    return allowed_recipients(sender).filter(pk=recipient.pk).exists()


def send_message(sender, recipient, subject, body, parent=None):
    if not can_message(sender, recipient):
        raise PermissionDenied
    msg = Message.objects.create(sender=sender, recipient=recipient, subject=subject.strip()[:150], body=body, parent=parent)
    notify([recipient], f"New message from {sender.get_full_name() or sender.username}: {msg.subject}", f"/messages/{msg.pk}/", "message")
    return msg


def unread_messages(user):
    return Message.objects.filter(recipient=user, read_at__isnull=True, recipient_deleted=False).count()


def inbox(user):
    return Message.objects.filter(recipient=user, recipient_deleted=False).select_related("sender")


def sent(user):
    return Message.objects.filter(sender=user, sender_deleted=False).select_related("recipient")


def thread_for(msg):
    """The whole conversation this message belongs to (walks up to the first message, then down)."""
    root = msg
    for _ in range(50):
        if root.parent_id is None:
            break
        root = root.parent
    out, frontier = [root], [root.pk]
    while frontier and len(out) < 100:
        kids = list(Message.objects.filter(parent_id__in=frontier).select_related("sender", "recipient").order_by("created_at", "id"))
        out += kids
        frontier = [k.pk for k in kids]
    return sorted(out, key=lambda m: (m.created_at, m.pk))


def visible_thread(user, msg):
    """Messages of the thread that this user took part in and has not deleted."""
    return [m for m in thread_for(msg) if (m.sender_id == user.pk and not m.sender_deleted) or (m.recipient_id == user.pk and not m.recipient_deleted)]


# ---------- announcements ----------

def can_announce(user, course):
    if course is None:
        return user.role == "admin"
    return perm.can_manage(user, course)


def announce(author, course, title, body, priority="normal", pinned=False, draft=False):
    if not can_announce(author, course):
        raise PermissionDenied
    a = Announcement.objects.create(course=course, author=author, title=title.strip()[:150], body=body,
                                    priority=priority, pinned=pinned, is_draft=draft)
    if not draft:
        notify_announcement(a)
    return a


def notify_announcement(a):
    """Tell everyone in the announcement's audience (the author excluded)."""
    if a.course_id is None:
        audience = User.objects.filter(is_active=True).exclude(pk=a.author_id)
        where = "the whole site"
    else:
        audience = User.objects.filter(is_active=True).filter(
            Q(enrolments__course=a.course, enrolments__status=Enrolment.Status.ACTIVE) | Q(teaching_courses=a.course)).exclude(pk=a.author_id).distinct()
        where = a.course.code
    prefix = "Urgent announcement" if a.priority == "urgent" else "Announcement"
    notify(audience, f"{prefix} ({where}): {a.title}", "/announcements/", "announcement")


def announcements_for(user, drafts=True):
    """Published announcements the user may see, plus their own drafts."""
    if user.role == "admin":
        qs = Announcement.objects.select_related("course", "author")
    else:
        ids = list(perm.visible_courses_for(user).values_list("pk", flat=True))
        qs = Announcement.objects.filter(Q(course__isnull=True) | Q(course_id__in=ids)).select_related("course", "author")
    return qs.filter(Q(is_draft=False) | Q(author=user)) if drafts else qs.filter(is_draft=False)


# ---------- forums ----------

def can_use_forum(user, course):
    return perm.can_view(user, course)


def can_reply(user, topic):
    return can_use_forum(user, topic.course) and (not topic.locked or perm.can_manage(user, topic.course))


def _staff_of(course):
    return list(course.lecturers.all())


def create_topic(user, course, title, body):
    if not can_use_forum(user, course):
        raise PermissionDenied
    topic = ForumTopic.objects.create(course=course, author=user, title=title.strip()[:150])
    ForumPost.objects.create(topic=topic, author=user, body=body)
    notify([l for l in _staff_of(course) if l.pk != user.pk], f"New forum topic in {course.code}: {topic.title}", f"/forums/topic/{topic.pk}/", "forum")
    return topic


def reply(user, topic, body):
    if not can_reply(user, topic):
        raise PermissionDenied
    post = ForumPost.objects.create(topic=topic, author=user, body=body)
    ForumTopic.objects.filter(pk=topic.pk).update(last_post_at=timezone.now())
    who = [topic.author] + _staff_of(topic.course) + [p.author for p in topic.posts.select_related("author").exclude(pk=post.pk)]
    notify([u for u in who if u.pk != user.pk], f"New reply in {topic.course.code}: {topic.title}", f"/forums/topic/{topic.pk}/", "forum")
    return post
