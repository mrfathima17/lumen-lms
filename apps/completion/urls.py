from django.urls import path

from . import views

app_name = "completion"

urlpatterns = [
    path("completion/", views.mine, name="mine"),
    path("completion/<int:course_id>/", views.mine_course, name="mine-course"),
    path("certificates/", views.certificates, name="certificates"),
    path("certificates/<str:code>/pdf/", views.certificate_pdf, name="pdf"),
    path("verify/<str:code>/", views.verify, name="verify"),
    path("completion-manager/", views.manage_list, name="manage-list"),
    path("completion-manager/<int:course_id>/", views.manage, name="manage"),
    path("completion-manager/<int:course_id>/issue/", views.issue_all, name="issue-all"),
    path("completion-manager/certificates/<int:cert_id>/revoke/", views.revoke, name="revoke"),
]
