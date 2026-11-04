from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("attendance/", views.course_list, name="course-list"),
    path("attendance/course/<int:course_id>/", views.course_attendance, name="course"),
    path("attendance/course/<int:course_id>/sessions/new/", views.session_new, name="session-new"),
    path("attendance/course/<int:course_id>/export/", views.export_csv, name="export"),
    path("attendance/sessions/<int:session_id>/", views.sheet, name="sheet"),
    path("attendance/sessions/<int:session_id>/delete/", views.session_delete, name="session-delete"),
    path("my-attendance/", views.my_attendance, name="my-attendance"),
]
