from django.urls import path

from . import views

app_name = "sitting"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("application/", views.application_status, name="application_status"),
    path("jobs/", views.find_jobs, name="sitter_find_jobs"),
    path("my-jobs/", views.my_jobs, name="sitter_my_jobs"),
    path("earnings/", views.earnings, name="sitter_earnings"),
    path("profile/", views.profile, name="sitter_profile"),
]
