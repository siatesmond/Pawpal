from django.urls import path

from .views import (
    BookingDetailView,
    BookingListView,
    OrderDetailView,
    OrderListView,
    CustomerHomeView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    CustomerProfileView,
    AddAddressView,
    AddPetView,
    EditAddressView,
    EditPetView,
    DeletePetView,
    PetListView,
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
    path("profile/", CustomerProfileView.as_view(), name="profile"),
    path("profile/address/add/", AddAddressView.as_view(), name="add_address"),
    path(
        "profile/address/<int:address_id>/edit/",
        EditAddressView.as_view(),
        name="edit_address",
    ),
    path("bookings/", BookingListView.as_view(), name="bookings"),
    path("bookings/<int:booking_id>/", BookingDetailView.as_view(), name="booking_detail"),
    path("orders/", OrderListView.as_view(), name="orders"),
    path("orders/<int:order_id>/", OrderDetailView.as_view(), name="order_detail"),
    path("pets/", PetListView.as_view(), name="pets"),
    path("pets/add/", AddPetView.as_view(), name="add_pet"),
    path("pets/<int:pet_id>/edit/", EditPetView.as_view(), name="edit_pet"),
    path("pets/<int:pet_id>/delete/", DeletePetView.as_view(), name="delete_pet"),
    path("cart/", views.cart, name="customer_cart"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="customer_add_to_cart"),
    path("cart/item/<int:item_id>/increment/", views.increment_cart_item,name="increment_cart_item"),
    path("cart/item/<int:item_id>/decrement/", views.decrement_cart_item,name="decrement_cart_item")
]
