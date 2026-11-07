from django.contrib import admin
from django.urls import path

from . import views

app_name = 'payment'

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/success/", views.checkout_success, name="checkout_success"),
]