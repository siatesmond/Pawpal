from django.urls import path

from .views import (
    CustomerHomeView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    RegisterView,
    ResendOTPView,
    VerifyOTPView,
)

from . import views

app_name = "user"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot_password"),
    path("verify/", VerifyOTPView.as_view(), name="verify_otp"),
    path("verify/resend/", ResendOTPView.as_view(), name="resend_otp"),
    path("register/", RegisterView.as_view(), name="register"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("home/", CustomerHomeView.as_view(), name="customer_home"),
    path("cart/", views.cart, name="customer_cart"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="customer_add_to_cart"),
    path("cart/item/<int:item_id>/increment/", views.increment_cart_item,name="increment_cart_item"),
    path("cart/item/<int:item_id>/decrement/", views.decrement_cart_item,name="decrement_cart_item")
]
