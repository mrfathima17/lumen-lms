from django.urls import path

from . import views

app_name = "surveys"

urlpatterns = [
    path("surveys/", views.student_list, name="student-list"),
    path("surveys/<int:pk>/", views.student_detail, name="student-detail"),
    path("survey-manager/", views.manage_list, name="manage-list"),
    path("survey-manager/new/<int:course_id>/", views.survey_edit, name="new"),
    path("survey-manager/<int:pk>/", views.editor, name="editor"),
    path("survey-manager/<int:pk>/edit/", views.survey_edit, name="edit"),
    path("survey-manager/<int:pk>/delete/", views.survey_delete, name="delete"),
    path("survey-manager/<int:pk>/results/", views.staff_results, name="results"),
    path("survey-manager/<int:pk>/export/", views.export, name="export"),
    path("survey-manager/<int:survey_id>/questions/new/", views.question_edit, name="question-new"),
    path("survey-manager/questions/<int:pk>/edit/", views.question_edit, name="question-edit"),
    path("survey-manager/questions/<int:pk>/delete/", views.question_delete, name="question-delete"),
]
