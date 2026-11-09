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
    path("staff/products/", views.staff_products, name="staff_products"),
    path("staff/products/add/", views.product_form, name="add_product"),
    path("staff/products/<int:pk>/edit/", views.product_form, name="update_product"),
    path("staff/bookings/", views.bookings, name="staff_bookings"),
    path("staff/bookings/<int:pk>/edit/", views.update_booking, name="update_booking"),
    path("staff/bookings/updates/<int:pk>/edit/", views.edit_booking_update, name="edit_booking_update"),
    path("staff/bookings/updates/<int:pk>/delete/", views.delete_booking_update, name="delete_booking_update"),
]