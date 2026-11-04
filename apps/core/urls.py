from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.public_home, name="public-home"),
    path("terms/", views.terms, name="terms"),
    path("help/", views.help_page, name="help"),
    path("session-expired/", views.session_expired, name="session-expired"),
    path("healthz/", views.healthz, name="healthz"),
    path("branding/<str:kind>/", views.brand_asset, name="brand-asset"),
]
