from django.urls import path

from .views import (
    CustomerHomeView,
    LoginView,
    LogoutView,
    RegisterView,
    ResendOTPView,
    VerifyOTPView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("register/", RegisterView.as_view(), name="register"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("home/", CustomerHomeView.as_view(), name="customer_home"),
    path("verify/", VerifyOTPView.as_view(), name="verify_otp"),
    path("verify/resend/", ResendOTPView.as_view(), name="resend_otp"),
]
