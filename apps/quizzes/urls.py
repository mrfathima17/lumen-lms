from django.urls import path

from . import views, views_bank as vb

app_name = "quizzes"

urlpatterns = [
    # students (network rule scope "quiz" applies to /quizzes/)
    path("quizzes/", views.student_list, name="student-list"),
    path("quizzes/<int:pk>/", views.student_detail, name="student-detail"),
    path("quizzes/<int:pk>/start/", views.start, name="start"),
    path("quizzes/attempt/<int:attempt_id>/", views.attempt_view, name="attempt"),
    path("quizzes/attempt/<int:attempt_id>/answer/<int:question_id>/", views.save_answer, name="save-answer"),
    path("quizzes/attempt/<int:attempt_id>/finish/", views.finish, name="finish"),
    path("quizzes/attempt/<int:attempt_id>/result/", views.result, name="result"),
    # staff
    path("quiz-manager/", views.manage_list, name="manage-list"),
    path("quiz-manager/course/<int:course_id>/new/", views.quiz_edit, name="new"),
    path("quiz-manager/<int:pk>/", views.editor, name="editor"),
    path("quiz-manager/<int:pk>/edit/", views.quiz_edit, name="edit"),
    path("quiz-manager/<int:pk>/action/<str:action>/", views.quiz_action, name="action"),
    path("quiz-manager/<int:pk>/questions/new/", views.question_edit, name="question-new"),
    path("quiz-manager/questions/<int:question_id>/edit/", views.question_edit, name="question-edit"),
    path("quiz-manager/questions/<int:question_id>/delete/", views.question_delete, name="question-delete"),
    path("quiz-manager/<int:pk>/attempts/", views.attempts_list, name="attempts"),
    path("quiz-manager/attempts/<int:attempt_id>/grade/", views.grade_attempt, name="grade"),
    path("quiz-manager/attempts/<int:attempt_id>/regrade/", views.regrade_attempt, name="regrade"),
    path("quiz-manager/attempts/<int:attempt_id>/reset/", views.reset_attempt, name="reset"),
    path("quiz-manager/<int:pk>/marking/", views.marking, name="marking"),
    path("quiz-manager/bank/", vb.bank_courses, name="bank-list-all"),
    path("quiz-manager/bank/template.csv", vb.bank_template, name="bank-template"),
    path("quiz-manager/bank/course/<int:course_id>/", vb.bank_list, name="bank-list"),
    path("quiz-manager/bank/course/<int:course_id>/new/", vb.bank_edit, name="bank-new"),
    path("quiz-manager/bank/course/<int:course_id>/import/", vb.bank_import, name="bank-import"),
    path("quiz-manager/bank/course/<int:course_id>/import/confirm/", vb.bank_import_confirm, name="bank-import-confirm"),
    path("quiz-manager/bank/course/<int:course_id>/export/", vb.bank_export, name="bank-export"),
    path("quiz-manager/bank/course/<int:course_id>/add-to-quiz/", vb.bank_add_to_quiz, name="bank-add-to-quiz"),
    path("quiz-manager/bank/<int:pk>/edit/", vb.bank_edit, name="bank-edit"),
    path("quiz-manager/bank/<int:pk>/delete/", vb.bank_delete, name="bank-delete"),
    path("quiz-manager/questions/<int:question_id>/to-bank/", vb.question_to_bank, name="question-to-bank"),
]
