from django.contrib import admin

from .models import Announcement, ForumPost, ForumTopic, Message, Notification

for m in (Message, ForumTopic, ForumPost, Announcement, Notification):
    admin.site.register(m)
