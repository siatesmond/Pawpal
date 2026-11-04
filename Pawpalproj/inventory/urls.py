from django.contrib import admin
from django.urls import path, include

from . import views

app_name = "inventory"

urlpatterns = [
    path("loaddata/", views.loadData, name="loadData"),
    path("products/", views.product_list, name="product_list"),
    path("products/<int:product_id>/", views.product_detail, name="product_detail"),
    path("staff/orders-stock/", views.staff_orders_stock, name="staff_orders_stock"),
    path('stock/<int:pk>/update/', views.update_stock, name='update_stock'),
]