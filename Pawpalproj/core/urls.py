from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # fill the database with the demo data (core/mock_data.py)
    path("loadData/", views.loadData, name="load_data"),
    # business owner: dashboard
    path("admin-panel/", views.owner_dashboard, name="owner_dashboard"),
    # business owner: customers
    path("admin-panel/customers/", views.owner_customers, name="owner_customers"),
    path(
        "admin-panel/customers/<int:pk>/edit/",
        views.owner_edit_customer,
        name="owner_edit_customer",
    ),
    path(
        "admin-panel/customers/<int:pk>/points/",
        views.owner_adjust_points,
        name="owner_adjust_points",
    ),
    # business owner: pet sitter applications
    path("admin-panel/pet-sitters/", views.owner_sitters, name="owner_sitters"),
    path(
        "admin-panel/pet-sitters/<int:pk>/review/",
        views.owner_review_sitter,
        name="owner_review_sitter",
    ),
    # business owner: sitting requests
    path("admin-panel/sitting-requests/", views.owner_sitting_requests, name="owner_sitting_requests"),
    path("admin-panel/sitting-requests/<int:pk>/cancel/", views.owner_cancel_sitting, name="owner_cancel_sitting"),
    # business owner: staff
    path("admin-panel/staff/", views.owner_staff, name="owner_staff"),
    path("admin-panel/staff/add/", views.owner_add_staff, name="owner_add_staff"),
    path("admin-panel/staff/<int:pk>/edit/", views.owner_edit_staff, name="owner_edit_staff"),
    path(
        "admin-panel/staff/<int:pk>/toggle/",
        views.owner_toggle_staff,
        name="owner_toggle_staff",
    ),
]
