from django.urls import path

from . import views

app_name = "grading"

urlpatterns = [
    path("gradebook/", views.gradebook_list, name="gradebook-list"),
    path("gradebook/<int:course_id>/", views.gradebook, name="gradebook"),
    path("gradebook/<int:course_id>/items/new/", views.item_add, name="item-add"),
    path("gradebook/<int:course_id>/publish/", views.publish, name="publish"),
    path("gradebook/<int:course_id>/export/", views.export_csv, name="export"),
    path("gradebook/items/<int:item_id>/edit/", views.item_edit, name="item-edit"),
    path("gradebook/items/<int:item_id>/delete/", views.item_delete, name="item-delete"),
    path("gradebook/items/<int:item_id>/marks/", views.manual_marks, name="manual-marks"),
    path("grades/", views.my_grades, name="my-grades"),
    path("grades/<int:course_id>/", views.my_course_grades, name="my-course-grades"),
    path("results/", views.my_results, name="my-results"),
]
