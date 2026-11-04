from django.urls import path

from . import views

app_name = "files"

urlpatterns = [
    path("files/", views.file_list, name="list"),
    path("files/upload/", views.upload, name="upload"),
    path("files/<int:file_id>/download/", views.download, name="download"),
    path("files/<int:file_id>/delete/", views.delete, name="delete"),
]
