from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("sign-in/", views.SignInView.as_view(), name="login"),
    path("sign-in/verify/", views.two_factor_verify, name="two-factor-verify"),
    path("profile/two-factor/", views.two_factor_settings, name="two-factor"),
    path("profile/two-factor/start/", views.two_factor_start, name="two-factor-start"),
    path("profile/two-factor/confirm/", views.two_factor_confirm, name="two-factor-confirm"),
    path("profile/two-factor/codes/", views.two_factor_new_codes, name="two-factor-codes"),
    path("profile/two-factor/disable/", views.two_factor_disable, name="two-factor-disable"),
    path("forgot-password/", views.forgot_password, name="forgot-password"),
    path("reset/<str:uidb64>/<str:token>/", views.password_reset_confirm, name="password-reset-confirm"),
    path("sign-out/", views.sign_out, name="logout"),
    path("home/", views.home, name="home"),
    path("password/change/", views.password_change, name="password-change"),
    path("profile/", views.profile, name="profile"),
    path("profile/sign-out-others/", views.sign_out_others, name="sign-out-others"),
    path("people/<int:user_id>/", views.person, name="person"),
    path("search/", views.search, name="search"),
    path("student/customise/", views.customise_dashboard, name="customise-dashboard"),
    path("student/", views.student_dashboard, name="student-dashboard"),
    path("lecturer/", views.lecturer_dashboard, name="lecturer-dashboard"),
    path("admin-panel/", views.admin_overview, name="admin-overview"),
]
