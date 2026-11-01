from core.models import Outlet
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

IMAGE_TYPES = FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])

pet_profile_images = FileSystemStorage(
    location=settings.BASE_DIR / "user" / "static" / "user" / "images",
    base_url="/static/user/images/",
)


# Create your models here.
# User
#  -- Customer
#  -- Staff
#  -- BusinessOwner
# Pet
# Address
# OTP


class User(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    mobile = models.CharField(max_length=8, blank=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_business_owner = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.username


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
    outlet = models.ForeignKey(
        Outlet, on_delete=models.CASCADE, related_name="staff_members"
    )


class BusinessOwner(User):
    pass


class Address(models.Model):
    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=6)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="addresses"
    )

    def __str__(self):
        return f"{self.line1}, {self.line2}, {self.postal_code}"


class Pet(models.Model):

    class PetType(models.TextChoices):
        DOG = "DOG", "Dog"
        CAT = "CAT", "Cat"
        OTHER = "OTHER", "Other"

    name = models.CharField(max_length=100)
    profile_picture = models.FileField(
        storage=pet_profile_images, validators=[IMAGE_TYPES], blank=True
    )
    pet_type = models.CharField(max_length=10, choices=PetType.choices)
    breed = models.CharField(max_length=50, blank=True)
    age = models.PositiveIntegerField()
    owner_id = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="pets"
    )

    def __str__(self):
        return f"{self.name} ({self.species})"


class OTP(models.Model):
    class Purpose(models.TextChoices):
        REGISTER = "register", "Verify account"
        PASSWORD_RESET = "password_reset", "Reset password"

    VALID_MINUTES = 5
    MAX_ATTEMPTS = 5

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otps")
    code_hash = models.CharField(max_length=128)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() > self.expires_at
