from django.urls import path

from . import views

app_name = "service"

urlpatterns = [
    path("loaddata/", views.loadData, name="loadData"),
    path("book/", views.book, name="book"),
    path("book/checkout/", views.book_checkout, name="book_checkout"),
    path("book/success/", views.book_success, name="book_success"),
]
