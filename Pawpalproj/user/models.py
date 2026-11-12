from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import Outlet

# Models in this file:
# User
#  -- Customer
#  -- Staff
#  -- BusinessOwner
#  -- PetSitter  (in sitting/models.py)
# Address
# Pet
# OTP


# Checks used by the fields below

# Singapore phone numbers: exactly 8 digits, e.g. 91234567
MOBILE_VALIDATOR = RegexValidator(r"^[0-9]{8}$", "Mobile number must be 8 digits, e.g. 91234567.")

IMAGE_TYPES = FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])


def check_email_domain(email):
    # Django already checks the basic format; this also needs a dot after the @,
    # so "amy@localhost" or "amy@gmail" are not accepted
    domain = email.rsplit("@", 1)[-1]
    if "." not in domain:
        raise ValidationError("Enter a full email address, e.g. name@example.com.")


# Pet photos are saved in user/static/user/images/
pet_profile_images = FileSystemStorage(
    location=settings.BASE_DIR / "user" / "static" / "user" / "images",
    base_url="/static/user/images/",
)


# Users

class User(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True, validators=[check_email_domain])
    password = models.CharField(max_length=128)  # only the hash, never the real password
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    mobile = models.CharField(max_length=8, validators=[MOBILE_VALIDATOR], help_text="8 digits, e.g. 91234567")
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_business_owner = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.username

    # Same as Django's set_password(): saves a salted PBKDF2 hash
    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    # Same as Django's check_password(): compares a typed password with the hash
    def check_password(self, raw_password):
        return check_password(raw_password, self.password)


class Customer(User):
    point_balance = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(point_balance__gte=0),
                name="customer_point_balance_non_negative",
            )
        ]


class Staff(User):
    outlet = models.ForeignKey(Outlet, on_delete=models.CASCADE, related_name="staff_members")


class BusinessOwner(User):
    pass


# Customer details

class Address(models.Model):
    label = models.CharField(max_length=50, default="Address")
    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=6)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="addresses")
    is_default = models.BooleanField(default=False)

    def __str__(self):
        address = f"{self.line1}, {self.line2}, {self.postal_code}"
        if self.label:
            return f"{self.label} - {address}"
        return address


class Pet(models.Model):

    class PetType(models.TextChoices):
        DOG = "DOG", "Dog"
        CAT = "CAT", "Cat"
        OTHER = "OTHER", "Other"

    name = models.CharField(max_length=100)
    profile_picture = models.FileField(storage=pet_profile_images, validators=[IMAGE_TYPES], blank=True)
    pet_type = models.CharField(max_length=10, choices=PetType.choices)
    breed = models.CharField(max_length=50, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    medical_notes = models.TextField(blank=True)  # allergies, conditions, medication
    allergies = models.CharField(max_length=255, blank=True)
    conditions = models.CharField(max_length=255, blank=True)
    medication = models.CharField(max_length=255, blank=True)
    behaviour_notes = models.TextField(blank=True)  # handling tips, triggers
    last_vaccination_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    owner_id = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="pets")

    def __str__(self):
        return f"{self.name} ({self.get_pet_type_display()})"

    def get_emoji(self):
        # shown when the pet has no photo
        if self.pet_type == "DOG":
            return "🐶"
        if self.pet_type == "CAT":
            return "🐱"
        return "🐾"

    def get_age(self):
        # e.g. "3 yrs" or "8 mths"; empty when the birthday is not known
        if not self.date_of_birth:
            return ""
        months = (timezone.localdate() - self.date_of_birth).days * 12 // 365
        if months < 12:
            if months == 1:
                return "1 mth"
            return f"{months} mths"
        years = months // 12
        if years == 1:
            return "1 yr"
        return f"{years} yrs"


# One-time codes sent by email

class OTP(models.Model):

    class Purpose(models.TextChoices):
        REGISTER = "register", "Verify account"
        PASSWORD_RESET = "password_reset", "Reset password"

    VALID_MINUTES = 5
    MAX_ATTEMPTS = 5

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otps")
    code_hash = models.CharField(max_length=128)  # the code is hashed, like a password
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() > self.expires_at
