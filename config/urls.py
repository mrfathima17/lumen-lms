from django.contrib import admin
from django.urls import include, path

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.not_found"

urlpatterns = [
    path("django-admin/", admin.site.urls),  # raw Django admin, for developers only
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.courses.urls")),
    path("", include("apps.content.urls")),
    path("", include("apps.assignments.urls")),
    path("", include("apps.quizzes.urls")),
    path("", include("apps.grading.urls")),
    path("", include("apps.attendance.urls")),
    path("", include("apps.schedule.urls")),
    path("", include("apps.messaging.urls")),
    path("", include("apps.files.urls")),
    path("", include("apps.completion.urls")),
    path("", include("apps.surveys.urls")),
    path("", include("apps.administration.urls")),
]
