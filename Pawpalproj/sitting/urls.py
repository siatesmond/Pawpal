from django.urls import path

from . import views

app_name = "sitting"

urlpatterns = [
    # pet sitter side
    path("signup/", views.signup, name="signup"),
    path("application/", views.application_status, name="application_status"),
    path("jobs/", views.find_jobs, name="sitter_find_jobs"),
    path("my-jobs/", views.my_jobs, name="sitter_my_jobs"),
    path("earnings/", views.earnings, name="sitter_earnings"),
    path("profile/", views.profile, name="sitter_profile"),
    # pet owner (customer) side: find a pet sitter
    path("find/", views.find_sitter, name="find_sitter"),
    path("sitters/<int:pk>/", views.sitter_public_profile, name="sitter_public_profile"),
    # pet owner (customer) side: my sitting requests
    path("requests/", views.my_sitting_requests, name="my_sitting_requests"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("requests/<int:pk>/pay/", views.pay_for_request, name="pay_for_request"),
    path("requests/<int:pk>/cancel/", views.cancel_request, name="cancel_request"),
]
