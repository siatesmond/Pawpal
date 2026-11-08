from django import forms
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password

from .models import Address, Customer, User


class LoginForm(forms.Form):

    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
    remember = forms.BooleanField(label="Remember me", required=False)

    # A function in Django to get the cleaned data after key in the field
    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")
        # Check email and password
        if email and password:
            # Check in sqlite and filter the email check for two condition
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            # if dh the user and password is wrong
            if user is None or not check_password(password, user.password):
                raise forms.ValidationError("Incorrect email or password.")
            cleaned_data["user"] = user

        return cleaned_data


class RegisterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = Customer
        fields = ["username", "first_name", "last_name", "email", "mobile"]

    def clean(self):
        cleaned_data = super().clean()
        # if the password is match with confirm password
        if cleaned_data.get("password") != cleaned_data.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        # save to database
        customer = super().save(commit=False)
        # store hashed with make_password() function
        customer.password = make_password(self.cleaned_data["password"])
        if commit:
            customer.save()
        return customer


class ProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Email changes require a separate verification flow, so keep it fixed here.
        self.fields["email"].disabled = True
        self.fields["email"].help_text = (
            "To change your email, please contact admin at "
            f"{settings.ADMIN_CONTACT_EMAIL}."
        )

    class Meta:
        model = Customer
        fields = ["first_name", "last_name", "username", "email", "mobile"]


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ["label", "line1", "line2", "postal_code", "is_default"]
        labels = {
            "label": "Address name",
            "line1": "Address line 1",
            "line2": "Address line 2",
            "postal_code": "Postal code",
            "is_default": "Make this my default address",
        }


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        label="Current password",
        widget=forms.PasswordInput,
    )
    new_password = forms.CharField(
        label="New password",
        min_length=8,
        widget=forms.PasswordInput,
    )
    confirm_password = forms.CharField(
        label="Confirm new password",
        min_length=8,
        widget=forms.PasswordInput,
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("new_password") != cleaned_data.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data


class ForgotPasswordEmailForm(forms.Form):
    email = forms.EmailField()


class ResetPasswordForm(forms.Form):
    password = forms.CharField(
        label="New password",
        min_length=8,
        widget=forms.PasswordInput,
    )
    confirm_password = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput,
    )

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("password") != cleaned_data.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data


class OTPForm(forms.Form):
    code = forms.CharField(
        label="6-digit code",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
            }
        ),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit():
            raise forms.ValidationError("The code should only contain numbers.")
        return code
