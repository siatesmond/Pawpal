from django import forms

from core.models import Outlet
from user.forms import MOBILE_INPUT, PASSWORD_HELP, check_password_strength
from user.models import Customer, Staff

# Forms in this file (all used by the business owner):
# OwnerCustomerForm   (edit a customer's details)
# OwnerStaffEditForm  (edit a staff member and their outlet)
# OwnerStaffForm      (add a new staff account)
# PointsAdjustmentForm  (add or deduct a customer's points, with a reason)
# RejectSitterForm      (the reason for rejecting a pet sitter application)


class OwnerCustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        widgets = {"mobile": MOBILE_INPUT}
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
        widgets = {"mobile": MOBILE_INPUT}
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
        label="Password",
        help_text=PASSWORD_HELP,
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput,
        label="Confirm password",
    )

    class Meta:
        model = Staff
        widgets = {"mobile": MOBILE_INPUT}
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

    def clean_password(self):
        password = self.cleaned_data["password"]
        check_password_strength(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        # only compare when the password itself passed its checks
        if cleaned_data.get("password") and cleaned_data.get("password") != cleaned_data.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        staff = super().save(commit=False)
        staff.set_password(self.cleaned_data["password"])
        staff.is_verified = True
        staff.is_active = True
        staff.is_staff = True
        if commit:
            staff.save()
        return staff


class PointsAdjustmentForm(forms.Form):
    points = forms.IntegerField(widget=forms.NumberInput(attrs={"placeholder": "e.g. 200 or -200"}))
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Goodwill for late pick-up"}),
        error_messages={"required": "A reason is required for every points adjustment."},
    )

    def __init__(self, *args, customer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer

    def clean_points(self):
        points = self.cleaned_data["points"]
        if points == 0:
            raise forms.ValidationError("Enter a number of points to add (e.g. 200) or deduct (e.g. -200).")
        # the balance can never go below 0
        if self.customer and self.customer.point_balance + points < 0:
            raise forms.ValidationError(
                f"Cannot deduct {-points} points. The customer only has {self.customer.point_balance}."
            )
        return points


class RejectSitterForm(forms.Form):
    # shown to the applicant on their status page and in the email
    rejection_reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Reason for rejection"}),
        error_messages={"required": "A rejection reason is required."},
    )
