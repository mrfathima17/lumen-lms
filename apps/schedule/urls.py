from django.urls import path

from . import views

app_name = "schedule"

urlpatterns = [
    path("calendar/", views.calendar, name="calendar"),
    path("calendar/events/new/", views.event_new, name="event-new"),
    path("calendar/events/<int:event_id>/delete/", views.event_delete, name="event-delete"),
    path("calendar/export.ics", views.export_ics, name="export-ics"),
    path("timetable/", views.timetable, name="timetable"),
    path("timetable/course/<int:course_id>/", views.course_timetable, name="course-timetable"),
    path("timetable/slots/<int:slot_id>/delete/", views.slot_delete, name="slot-delete"),
    path("todo/", views.todo, name="todo"),
    path("todo/add/", views.todo_add, name="todo-add"),
    path("todo/<int:todo_id>/toggle/", views.todo_toggle, name="todo-toggle"),
    path("todo/<int:todo_id>/delete/", views.todo_delete, name="todo-delete"),
]
