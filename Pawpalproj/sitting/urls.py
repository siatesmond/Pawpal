from django.urls import path

from .views import SitterApplicationStatusView, SitterSignupView

app_name = "sitting"

urlpatterns = [
    path("signup/", SitterSignupView.as_view(), name="signup"),
    path("application/", SitterApplicationStatusView.as_view(), name="application_status"),
]