from django import forms
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password

from .models import Address, Customer, Pet, User, check_email_domain

# Password rule for every form that sets a password
PASSWORD_HELP = (
    "At least 8 characters, with an uppercase letter, a lowercase letter, "
    "a number and a special character (e.g. ! @ # $)."
)


def check_password_strength(password):
    # lists everything the password is missing, e.g. "Password needs an uppercase letter and a number."
    missing = []
    if len(password) < 8:
        missing.append("at least 8 characters")
    if not any(char.isupper() for char in password):
        missing.append("an uppercase letter")
    if not any(char.islower() for char in password):
        missing.append("a lowercase letter")
    if not any(char.isdigit() for char in password):
        missing.append("a number")
    if all(char.isalnum() for char in password):
        missing.append("a special character (e.g. ! @ # $)")
    if missing:
        if len(missing) == 1:
            needs = missing[0]
        else:
            needs = ", ".join(missing[:-1]) + " and " + missing[-1]
        raise forms.ValidationError("Password needs " + needs + ".")


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


# Phone number box used by every form: digits only, 8 long
MOBILE_INPUT = forms.TextInput(
    attrs={"inputmode": "numeric", "maxlength": "8", "pattern": "[0-9]{8}", "title": "8 digits, e.g. 91234567"}
)


class RegisterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, help_text=PASSWORD_HELP)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = Customer
        fields = ["username", "first_name", "last_name", "email", "mobile"]
        widgets = {"mobile": MOBILE_INPUT}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # example text inside each box
        placeholders = {
            "username": "e.g. amytan",
            "first_name": "e.g. Amy",
            "last_name": "e.g. Tan",
            "email": "name@example.com",
            "mobile": "e.g. 91234567",
            "password": "Create a password",
            "confirm_password": "Type it again",
        }
        for name, text in placeholders.items():
            self.fields[name].widget.attrs["placeholder"] = text
        self.fields["first_name"].required = True
        self.fields["email"].widget.attrs["autocomplete"] = "email"

    def clean_email(self):
        # save emails in lowercase, so Amy@Example.com and amy@example.com are the same account
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        check_password_strength(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        # if the password is match with confirm password
        # only compare when the password itself passed its checks
        if cleaned_data.get("password") and cleaned_data.get("password") != cleaned_data.get("confirm_password"):
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
        # username and mobile share a row; email (locked) takes the last full row
        fields = ["first_name", "last_name", "username", "mobile", "email"]
        widgets = {"mobile": MOBILE_INPUT}


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


class PetForm(forms.ModelForm):
    class Meta:
        model = Pet
        fields = [
            "name",
            "breed",
            "date_of_birth",
            "weight_kg",
            "pet_type",
            "profile_picture",
            "allergies",
            "conditions",
            "medication",
            "behaviour_notes",
            "last_vaccination_date",
        ]
        labels = {
            "name": "Name *",
            "breed": "Breed",
            "date_of_birth": "Date of birth",
            "weight_kg": "Weight (kg)",
            "pet_type": "Species *",
            "profile_picture": "Pet photo",
            "allergies": "Allergies",
            "conditions": "Conditions",
            "medication": "Medication",
            "behaviour_notes": "Behaviour notes",
            "last_vaccination_date": "Last vaccination date",
        }
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "last_vaccination_date": forms.DateInput(attrs={"type": "date"}),
            "allergies": forms.TextInput(attrs={"placeholder": "e.g. chicken"}),
            "conditions": forms.TextInput(attrs={"placeholder": "e.g. sensitive skin"}),
            "medication": forms.TextInput(attrs={"placeholder": "e.g. none"}),
            "behaviour_notes": forms.Textarea(
                attrs={"placeholder": "e.g. nervous around dryers — use low setting"}
            ),
            "weight_kg": forms.NumberInput(attrs={"step": "0.1"}),
            "profile_picture": forms.FileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            ),
        }

    def clean_profile_picture(self):
        image = self.cleaned_data.get("profile_picture")
        if image and image.size >= 100 * 1024 * 1024:
            raise forms.ValidationError("The pet image must be 100 MB or smaller.")
        return image


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        label="Current password",
        widget=forms.PasswordInput,
    )
    new_password = forms.CharField(
        label="New password",
        help_text=PASSWORD_HELP,
        widget=forms.PasswordInput,
    )
    confirm_password = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput,
    )

    def clean_new_password(self):
        password = self.cleaned_data["new_password"]
        check_password_strength(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        # only compare when the new password itself passed its checks
        if cleaned_data.get("new_password") and cleaned_data.get("new_password") != cleaned_data.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data


class ForgotPasswordEmailForm(forms.Form):
    email = forms.EmailField()


class ResetPasswordForm(forms.Form):
    password = forms.CharField(
        label="New password",
        help_text=PASSWORD_HELP,
        widget=forms.PasswordInput,
    )
    confirm_password = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput,
    )

    def clean_password(self):
        password = self.cleaned_data["password"]
        check_password_strength(password)
        validate_password(password)  # Django's checks too (e.g. not a very common password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        # only compare when the password itself passed its checks
        if cleaned_data.get("password") and cleaned_data.get("password") != cleaned_data.get("confirm_password"):
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
