from decimal import Decimal

from django import forms
from django.contrib.auth.hashers import make_password
from django.core.validators import FileExtensionValidator

from user.models import User

from .models import PetSitter


class SitterRegistrationForm(forms.Form):
    full_name = forms.CharField(max_length=61)
    mobile = forms.CharField(max_length=20)
    email = forms.EmailField()
    service_area = forms.CharField(max_length=100)
    password = forms.CharField(min_length=8, widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)
    experience_years = forms.IntegerField(min_value=0, max_value=80)
    daily_rate = forms.DecimalField(
        min_value=Decimal("0.01"), max_digits=8, decimal_places=2
    )
    pet_experience = forms.MultipleChoiceField(
        choices=[
            ("Dogs", "Dogs"),
            ("Cats", "Cats"),
            ("Small animals", "Small animals"),
        ],
        widget=forms.CheckboxSelectMultiple,
    )
    bio = forms.CharField(widget=forms.Textarea, max_length=2000)
    id_document = forms.FileField(
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "pdf"])
        ]
    )
    terms = forms.BooleanField(
        label="I agree to Pawpal's sitter terms and 10% service fee"
    )

    def __init__(self, *args, sitter=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sitter = sitter
        if sitter:
            for name in ("password", "confirm_password", "id_document", "terms"):
                self.fields[name].required = False
            self.initial.update(
                {
                    "full_name": f"{sitter.first_name} {sitter.last_name}".strip(),
                    "mobile": sitter.mobile,
                    "email": sitter.email,
                    "service_area": sitter.service_area,
                    "experience_years": sitter.experience_years,
                    "daily_rate": sitter.daily_rate_cents / 100,
                    "pet_experience": sitter.pet_experience.split(", "),
                    "bio": sitter.bio,
                    "terms": True,
                }
            )
            if sitter.id_document:
                self.initial["id_document"] = sitter.id_document

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        users = User.objects.filter(email__iexact=email)
        if self.sitter:
            users = users.exclude(pk=self.sitter.pk)
        if users.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_mobile(self):
        mobile = self.cleaned_data["mobile"].strip()
        if not mobile.replace("+", "").replace(" ", "").isdigit():
            raise forms.ValidationError("Enter a valid mobile number.")
        return mobile

    def clean_id_document(self):
        document = self.cleaned_data.get("id_document")
        if document and document.size > 5 * 1024 * 1024:
            raise forms.ValidationError("The ID document must be 5 MB or smaller.")
        return document

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        if password and password != cleaned_data.get("confirm_password"):
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data

    def save(self):
        full_name = " ".join(self.cleaned_data["full_name"].split())
        first_name, *last_name = full_name.split(" ")

        if self.sitter:
            sitter = self.sitter
            sitter.email = self.cleaned_data["email"]
            sitter.first_name = first_name
            sitter.last_name = " ".join(last_name)
            sitter.mobile = self.cleaned_data["mobile"]
            if self.cleaned_data.get("password"):
                sitter.password = make_password(self.cleaned_data["password"])
        else:
            username = self.cleaned_data["email"].split("@", 1)[0]
            base_username = username
            suffix = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{suffix}"
                suffix += 1
            sitter = PetSitter(
                username=username,
                email=self.cleaned_data["email"],
                password=make_password(self.cleaned_data["password"]),
                first_name=first_name,
                last_name=" ".join(last_name),
                mobile=self.cleaned_data["mobile"],
            )

        sitter.service_area = self.cleaned_data["service_area"]
        sitter.experience_years = self.cleaned_data["experience_years"]
        sitter.daily_rate_cents = int(self.cleaned_data["daily_rate"] * 100)
        sitter.pet_experience = ", ".join(self.cleaned_data["pet_experience"])
        sitter.bio = self.cleaned_data["bio"]
        if self.cleaned_data.get("id_document"):
            sitter.id_document = self.cleaned_data["id_document"]
        sitter.application_status = PetSitter.Status.PENDING
        sitter.rejection_reason = ""
        sitter.save()
        return sitter
