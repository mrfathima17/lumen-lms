from django.urls import path

from . import views

app_name = "assignments"

urlpatterns = [
    path("assignments/", views.overview, name="overview"),
    path("assignments/<int:pk>/", views.detail, name="detail"),
    path("assignments/<int:pk>/edit/", views.edit, name="edit"),
    path("assignments/<int:pk>/submissions/", views.submissions, name="submissions"),
    path("assignments/extensions/", views.extensions_list, name="extensions-list"),
    path("assignments/<int:pk>/extensions/", views.extensions, name="extensions"),
    path("assignments/<int:pk>/extensions/<int:ext_id>/delete/", views.extension_delete, name="extension-delete"),
    path("courses/<int:course_id>/assignments/new/", views.edit, name="new"),
    path("submissions/<int:sub_id>/grade/", views.grade_view, name="grade"),
    path("submissions/<int:sub_id>/download/", views.submission_download, name="download"),
    path("assignments/<int:pk>/rubric/", views.rubric_editor, name="rubric"),
    path("assignments/<int:pk>/rubric/new/", views.criterion_edit, name="criterion-new"),
    path("assignments/<int:pk>/rubric/copy/", views.rubric_copy, name="rubric-copy"),
    path("rubric/<int:criterion_id>/edit/", views.criterion_edit, name="criterion-edit"),
    path("rubric/<int:criterion_id>/delete/", views.criterion_delete, name="criterion-delete"),
]
