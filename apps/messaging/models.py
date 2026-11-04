from django.conf import settings
from django.db import models


class Message(models.Model):
    """A private message. Each side can delete their own copy without affecting the other."""
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_messages")
    subject = models.CharField(max_length=150)
    body = models.TextField(max_length=5000)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replies")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    sender_deleted = models.BooleanField(default=False)
    recipient_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.sender} → {self.recipient}: {self.subject}"


class ForumTopic(models.Model):
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="forum_topics")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    title = models.CharField(max_length=150)
    pinned = models.BooleanField(default=False)
    locked = models.BooleanField(default=False, help_text="Only lecturers can reply to a locked topic.")
    created_at = models.DateTimeField(auto_now_add=True)
    last_post_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-pinned", "-last_post_at", "-id"]

    def __str__(self):
        return f"{self.course.code} · {self.title}"


class ForumPost(models.Model):
    topic = models.ForeignKey(ForumTopic, on_delete=models.CASCADE, related_name="posts")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="forum_posts")
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class Announcement(models.Model):
    """course empty means the whole site (admins only)."""
    course = models.ForeignKey("courses.Course", null=True, blank=True, on_delete=models.CASCADE, related_name="announcements")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    title = models.CharField(max_length=150)
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        IMPORTANT = "important", "Important"
        URGENT = "urgent", "Urgent"

    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    pinned = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=False, help_text="Drafts are visible only to their author and notify nobody.")

    class Meta:
        ordering = ["-pinned", "-created_at", "-id"]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, default="info")
    text = models.CharField(max_length=250)
    url = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "read_at"])]
