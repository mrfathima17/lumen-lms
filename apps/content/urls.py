from django.urls import path

from . import views

app_name = "content"

urlpatterns = [
    path("courses/<int:course_id>/materials/new/", views.add_resource, name="add"),
    path("resources/<int:resource_id>/view/", views.viewer, name="view"),
    path("resources/<int:resource_id>/raw/", views.raw, name="raw"),
    path("resources/<int:resource_id>/download/", views.download, name="download"),
    path("resources/<int:resource_id>/done/", views.toggle_done, name="done"),
    path("resources/<int:resource_id>/<str:action>/", views.resource_action, name="action"),
]
