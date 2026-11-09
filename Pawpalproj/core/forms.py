from django import forms
from django.contrib.auth.hashers import make_password

from core.models import Outlet
from user.models import Customer, Staff


class OwnerCustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["username", "first_name", "last_name", "email", "mobile"]
        labels = {
            "username": "Username",
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Email",
            "mobile": "Mobile",
        }


class OwnerStaffEditForm(forms.ModelForm):
    # Edit a staff member's details and move them to another outlet
    class Meta:
        model = Staff
        fields = ["first_name", "last_name", "email", "mobile", "outlet"]
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Email",
            "mobile": "Mobile",
            "outlet": "Outlet",
        }


class OwnerStaffForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput,
        min_length=8,
        label="Password",
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput,
        label="Confirm password",
    )

    class Meta:
        model = Staff
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "mobile",
            "outlet",
            "password",
            "confirm_password",
        ]
        labels = {
            "username": "Username",
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Email",
            "mobile": "Mobile",
            "outlet": "Outlet",
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("password") != cleaned_data.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        staff = super().save(commit=False)
        staff.password = make_password(self.cleaned_data["password"])
        staff.is_verified = True
        staff.is_active = True
        staff.is_staff = True
        if commit:
            staff.save()
        return staff
