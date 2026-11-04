from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("courses/", views.my_courses, name="my-courses"),
    path("courses/catalog/", views.catalog, name="catalog"),
    path("preview/", views.preview, name="preview"),
    path("preview/exit/", views.preview_exit, name="preview-exit"),
    path("courses/tools/students/", views.tool_list, {"tool": "students"}, name="tool-students"),
    path("courses/tools/reports/", views.tool_list, {"tool": "reports"}, name="tool-reports"),
    path("courses/tools/settings/", views.tool_list, {"tool": "settings"}, name="tool-settings"),
    path("courses/tools/add-material/", views.tool_list, {"tool": "add-material"}, name="tool-add-material"),
    path("courses/tools/groups/", views.tool_list, {"tool": "groups"}, name="tool-groups"),
    path("courses/<int:pk>/", views.course_detail, name="detail"),
    path("courses/<int:pk>/participants/", views.participants, name="participants"),
    path("courses/<int:pk>/participants/export/", views.participants_export, name="participants-export"),
    path("courses/<int:pk>/settings/", views.course_settings, name="settings"),
    path("courses/<int:pk>/reports/", views.course_reports, name="reports"),
    path("courses/<int:pk>/enrol-self/", views.self_enrol, name="self-enrol"),
    path("courses/<int:pk>/topics/add/", views.topic_add, name="topic-add"),
    path("courses/<int:pk>/topics/<int:topic_id>/<str:action>/", views.topic_action, name="topic-action"),
    path("courses/<int:pk>/enrol/", views.bulk_enrol, name="bulk-enrol"),
    path("courses/<int:pk>/enrolments/<int:enrolment_id>/<str:action>/", views.enrolment_action, name="enrolment-action"),
    path("courses/<int:pk>/groups/", views.groups, name="groups"),
    path("courses/<int:pk>/groups/<int:group_id>/<str:action>/", views.group_member, name="group-member"),
    path("admin-panel/courses/", views.admin_courses, name="admin-courses"),
    path("admin-panel/courses/new/", views.admin_course_edit, name="admin-course-new"),
    path("admin-panel/courses/<int:pk>/edit/", views.admin_course_edit, name="admin-course-edit"),
    path("admin-panel/categories/", views.admin_categories, name="admin-categories"),
    path("admin-panel/categories/<int:pk>/edit/", views.admin_category_edit, name="admin-category-edit"),
    path("admin-panel/categories/<int:pk>/delete/", views.admin_category_delete, name="admin-category-delete"),
]
