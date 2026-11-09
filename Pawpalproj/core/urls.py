from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("loadData/", views.loadData, name="load_data"),
    path(
        "loadData/staff-owner/",
        views.load_staff_owner_data,
        name="load_staff_owner_data",
    ),
    path("admin-panel/", views.owner_dashboard, name="owner_dashboard"),
    path("admin-panel/customers/", views.owner_customers, name="owner_customers"),
    path("admin-panel/pet-sitters/", views.owner_sitters, name="owner_sitters"),
    path("admin-panel/staff/", views.owner_staff, name="owner_staff"),
]
