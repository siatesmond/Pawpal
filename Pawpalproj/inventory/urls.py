from django.contrib import admin
from django.urls import path

from . import views

urlpatterns = [
    path("loaddata/", views.loadData, name="loadData"),
    path("products/", views.product_list, name="product_list"),
]