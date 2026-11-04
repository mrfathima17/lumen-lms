from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.core import audit
from apps.courses import permissions as perm
from apps.courses.models import Course

from . import services
from .forms import AnnouncementForm, ComposeForm, PostForm, ReplyForm, TopicForm
from .models import Announcement, ForumPost, ForumTopic, Message, Notification


# ---------------------------------------------------------------- messages

@login_required
def inbox(request):
    page = Paginator(services.inbox(request.user), 25).get_page(request.GET.get("page"))
    return render(request, "messaging/inbox.html", {"page": page, "box": "inbox"})


@login_required
def sent_box(request):
    page = Paginator(services.sent(request.user), 25).get_page(request.GET.get("page"))
    return render(request, "messaging/inbox.html", {"page": page, "box": "sent"})


@login_required
def compose(request):
    initial = {}
    to = request.GET.get("to", "")
    if to.isdigit():
        initial["recipient"] = int(to)
    form = ComposeForm(request.POST or None, sender=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        msg = services.send_message(request.user, form.cleaned_data["recipient"], form.cleaned_data["subject"], form.cleaned_data["body"])
        flash.success(request, "Message sent.")
        return redirect("messaging:detail", message_id=msg.pk)
    return render(request, "messaging/compose.html", {"form": form})


def _own_message(request, message_id):
    msg = get_object_or_404(Message.objects.select_related("sender", "recipient"), pk=message_id)
    mine = (msg.sender_id == request.user.pk and not msg.sender_deleted) or (msg.recipient_id == request.user.pk and not msg.recipient_deleted)
    if not mine:
        raise PermissionDenied
    return msg


@login_required
def detail(request, message_id):
    msg = _own_message(request, message_id)
    if msg.recipient_id == request.user.pk and msg.read_at is None:
        Message.objects.filter(pk=msg.pk, read_at__isnull=True).update(read_at=timezone.now())
    thread = services.visible_thread(request.user, msg)
    other = msg.sender if msg.recipient_id == request.user.pk else msg.recipient
    box = "inbox" if msg.recipient_id == request.user.pk else "sent"
    page = Paginator(services.inbox(request.user) if box == "inbox" else services.sent(request.user), 25).get_page(1)
    return render(request, "messaging/detail.html", {"msg": msg, "thread": thread, "other": other, "form": ReplyForm(), "page": page, "box": box,
                                                      "can_reply": services.can_message(request.user, other)})


@require_POST
@login_required
def reply_message(request, message_id):
    msg = _own_message(request, message_id)
    other = msg.sender if msg.recipient_id == request.user.pk else msg.recipient
    form = ReplyForm(request.POST)
    if not form.is_valid():
        flash.error(request, "Write a reply (up to 5000 characters).")
        return redirect("messaging:detail", message_id=msg.pk)
    subject = msg.subject if msg.subject.lower().startswith("re:") else f"Re: {msg.subject}"
    new = services.send_message(request.user, other, subject, form.cleaned_data["body"], parent=msg)
    flash.success(request, "Reply sent.")
    return redirect("messaging:detail", message_id=new.pk)


@require_POST
@login_required
def delete_message(request, message_id):
    msg = _own_message(request, message_id)
    if msg.sender_id == request.user.pk:
        msg.sender_deleted = True
    if msg.recipient_id == request.user.pk:
        msg.recipient_deleted = True
    msg.save(update_fields=["sender_deleted", "recipient_deleted"])
    if msg.sender_deleted and msg.recipient_deleted:
        msg.delete()
    flash.success(request, "Message deleted.")
    return redirect("messaging:inbox")


# ---------------------------------------------------------------- forums

@login_required
def forums(request):
    courses = perm.visible_courses_for(request.user).select_related("semester").annotate(topic_count=Count("forum_topics", distinct=True))
    return render(request, "messaging/forums.html", {"courses": courses})


def _forum_course(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not services.can_use_forum(request.user, course):
        raise PermissionDenied
    return course


@login_required
def forum(request, course_id):
    course = _forum_course(request, course_id)
    topics = course.forum_topics.select_related("author").annotate(post_count=Count("posts"))
    others = [c for c in perm.visible_courses_for(request.user).order_by("code") if services.can_use_forum(request.user, c)]
    topics = list(topics)
    for t in topics:
        t.replies = max(t.post_count - 1, 0)
    pick = request.GET.get("t", "")
    current = next((t for t in topics if str(t.pk) == pick), topics[0] if topics else None)
    posts = list(current.posts.select_related("author")) if current else []
    manage = perm.can_manage(request.user, course)
    return render(request, "messaging/forum.html", {"course": course, "topics": topics, "course_chips": others, "current": current, "posts": posts, "manage": manage,
                                                    "can_reply": bool(current) and services.can_reply(request.user, current), "form": PostForm()})


@login_required
def topic_new(request, course_id):
    course = _forum_course(request, course_id)
    form = TopicForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        t = services.create_topic(request.user, course, form.cleaned_data["title"], form.cleaned_data["body"])
        return redirect("messaging:topic", topic_id=t.pk)
    return render(request, "messaging/topic_form.html", {"course": course, "form": form})


def _topic(request, topic_id):
    t = get_object_or_404(ForumTopic.objects.select_related("course", "author"), pk=topic_id)
    if not services.can_use_forum(request.user, t.course):
        raise PermissionDenied
    return t


@login_required
def topic(request, topic_id):
    t = _topic(request, topic_id)
    manage = perm.can_manage(request.user, t.course)
    form = PostForm(request.POST or None)
    if request.method == "POST":
        if not services.can_reply(request.user, t):
            raise PermissionDenied
        if form.is_valid():
            services.reply(request.user, t, form.cleaned_data["body"])
            return redirect("messaging:topic", topic_id=t.pk)
    posts = t.posts.select_related("author")
    return render(request, "messaging/topic.html", {"topic": t, "posts": posts, "form": form, "manage": manage, "can_reply": services.can_reply(request.user, t)})


@require_POST
@login_required
def topic_flag(request, topic_id, flag):
    t = _topic(request, topic_id)
    if flag not in ("pinned", "locked") or not perm.can_manage(request.user, t.course):
        raise PermissionDenied
    setattr(t, flag, not getattr(t, flag))
    t.save(update_fields=[flag])
    return redirect("messaging:topic", topic_id=t.pk)


@require_POST
@login_required
def topic_delete(request, topic_id):
    t = _topic(request, topic_id)
    if not perm.can_manage(request.user, t.course):
        raise PermissionDenied
    cid = t.course_id
    audit.record(request, "forum_topic_deleted", target=t.course.code, detail=t.title)
    t.delete()
    flash.success(request, "Topic deleted.")
    return redirect("messaging:forum", course_id=cid)


@require_POST
@login_required
def post_delete(request, post_id):
    p = get_object_or_404(ForumPost.objects.select_related("topic__course"), pk=post_id)
    if not services.can_use_forum(request.user, p.topic.course):
        raise PermissionDenied
    if p.author_id != request.user.pk and not perm.can_manage(request.user, p.topic.course):
        raise PermissionDenied
    first = p.topic.posts.first()
    if first and first.pk == p.pk:
        flash.error(request, "The first post can only be removed by deleting the topic.")
    else:
        p.delete()
    return redirect("messaging:topic", topic_id=p.topic_id)


# ---------------------------------------------------------------- announcements

@login_required
def announcements(request):
    page = Paginator(services.announcements_for(request.user), 20).get_page(request.GET.get("page"))
    can_post = request.user.role in ("lecturer", "admin")
    return render(request, "messaging/announcements.html", {"page": page, "can_post": can_post})


@login_required
def announcement_new(request):
    if request.user.role not in ("lecturer", "admin"):
        raise PermissionDenied
    form = AnnouncementForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        draft = "draft" in request.POST
        a = services.announce(request.user, d["course"], d["title"], d["body"], d["priority"], d["pinned"], draft)
        audit.record(request, "announcement_posted", target=a.course.code if a.course else "site", detail=a.title + (" (draft)" if draft else ""))
        flash.success(request, "Draft saved. Nobody has been notified yet." if draft else "Announcement posted and everyone in the audience notified.")
        return redirect("messaging:announcements")
    return render(request, "messaging/announcement_form.html", {"form": form, "recent": _recent_announcements(request.user)})


def _recent_announcements(user):
    return Announcement.objects.filter(author=user).select_related("course").order_by("-created_at", "-id")[:6]


def _can_edit_announcement(user, a):
    return a.author_id == user.pk or user.role == "admin" or bool(a.course_id and perm.can_manage(user, a.course))


@login_required
def announcement_edit(request, announcement_id):
    a = get_object_or_404(Announcement.objects.select_related("course"), pk=announcement_id)
    if not _can_edit_announcement(request.user, a):
        raise PermissionDenied
    form = AnnouncementForm(request.POST or None, instance=a, user=request.user)
    form.fields["course"].disabled = True  # the audience of a posted announcement does not move
    if request.method == "POST" and form.is_valid():
        a = form.save()
        publishing = a.is_draft and "draft" not in request.POST
        if publishing:
            a.is_draft = False
            a.save(update_fields=["is_draft"])
            services.notify_announcement(a)
        audit.record(request, "announcement_edited", target=a.course.code if a.course else "site", detail=a.title)
        flash.success(request, "Announcement posted and everyone in the audience notified." if publishing else "Announcement updated.")
        return redirect("messaging:announcements")
    return render(request, "messaging/announcement_form.html", {"form": form, "recent": _recent_announcements(request.user), "editing": a})


@require_POST
@login_required
def announcement_delete(request, announcement_id):
    a = get_object_or_404(Announcement.objects.select_related("course"), pk=announcement_id)
    if not (a.author_id == request.user.pk or request.user.role == "admin" or (a.course_id and perm.can_manage(request.user, a.course))):
        raise PermissionDenied
    a.delete()
    flash.success(request, "Announcement deleted.")
    return redirect("messaging:announcements")


# ---------------------------------------------------------------- notifications

@login_required
def notifications(request):
    qs = Notification.objects.filter(user=request.user)
    only = request.GET.get("filter", "")
    if only == "unread":
        qs = qs.filter(read_at__isnull=True)
    elif only in ("message", "announcement", "forum", "grade"):
        qs = qs.filter(kind=only)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    tabs = [("", "All"), ("unread", "Unread"), ("message", "Messages"), ("announcement", "Announcements"), ("forum", "Forums"), ("grade", "Grades")]
    return render(request, "messaging/notifications.html", {"page": page, "only": only, "tabs": tabs})


@login_required
def notification_open(request, notification_id):
    n = get_object_or_404(Notification, pk=notification_id, user=request.user)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return redirect(services.safe_next(n.url) or "messaging:notifications")


@require_POST
@login_required
def notifications_read_all(request):
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return redirect("messaging:notifications")
