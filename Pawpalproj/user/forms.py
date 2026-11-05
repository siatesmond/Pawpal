from django import forms
from django.contrib.auth.hashers import check_password, make_password

from .models import Customer, User


class LoginForm(forms.Form):

    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
    remember = forms.BooleanField(required=False)

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
    confirm_password = forms.CharField(
        widget=forms.PasswordInput, label="Confirm password"
    )
    agree_terms = forms.BooleanField(
        label="I agree to the Terms and Privacy Policy",
        error_messages={"required": "Please agree to the Terms and Privacy Policy."},
    )

    class Meta:
        model = Customer
        fields = [
            "first_name",
            "last_name",
            "username",
            "email",
            "mobile",
        ]  # order shown on the page
        labels = {"mobile": "Mobile number (8 digits)"}

    # keep your existing clean() and save() below

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


class OTPForm(forms.Form):
    code = forms.CharField(
        label="6-digit code",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "placeholder": "123456",
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
