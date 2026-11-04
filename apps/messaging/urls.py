from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("messages/", views.inbox, name="inbox"),
    path("messages/sent/", views.sent_box, name="sent"),
    path("messages/new/", views.compose, name="compose"),
    path("messages/<int:message_id>/", views.detail, name="detail"),
    path("messages/<int:message_id>/reply/", views.reply_message, name="reply"),
    path("messages/<int:message_id>/delete/", views.delete_message, name="delete"),
    path("forums/", views.forums, name="forums"),
    path("forums/course/<int:course_id>/", views.forum, name="forum"),
    path("forums/course/<int:course_id>/new/", views.topic_new, name="topic-new"),
    path("forums/topic/<int:topic_id>/", views.topic, name="topic"),
    path("forums/topic/<int:topic_id>/toggle/<str:flag>/", views.topic_flag, name="topic-flag"),
    path("forums/topic/<int:topic_id>/delete/", views.topic_delete, name="topic-delete"),
    path("forums/post/<int:post_id>/delete/", views.post_delete, name="post-delete"),
    path("announcements/", views.announcements, name="announcements"),
    path("announcements/new/", views.announcement_new, name="announcement-new"),
    path("announcements/<int:announcement_id>/edit/", views.announcement_edit, name="announcement-edit"),
    path("announcements/<int:announcement_id>/delete/", views.announcement_delete, name="announcement-delete"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/read-all/", views.notifications_read_all, name="read-all"),
    path("notifications/<int:notification_id>/open/", views.notification_open, name="open"),
]
