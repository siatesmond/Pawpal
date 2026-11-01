from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.db.models import Q
from user.models import BusinessOwner, Customer, Pet, User

IMAGE_TYPES = FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])

sitting_images = FileSystemStorage(
    location=settings.BASE_DIR / "sitting" / "static" / "sitting" / "images",
    base_url="/static/sitting/images/",
)

update_images = FileSystemStorage(
    location=settings.BASE_DIR / "sitting" / "static" / "update" / "images",
    base_url="/static/update/images/",
)


# Create your models here.
# PetSitter
# SittingRequest
# SittingUpdate


class PetSitter(User):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    bio = models.TextField(blank=True)
    service_area = models.CharField(max_length=100)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    experience_years = models.PositiveIntegerField(default=0)
    pet_experience = models.CharField(max_length=100, blank=True)
    daily_rate_cents = models.PositiveIntegerField()
    id_document = models.FileField(
        storage=sitting_images, validators=[IMAGE_TYPES], blank=True
    )
    application_status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        BusinessOwner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_sitters",
    )
    applied_at = models.DateTimeField(auto_now_add=True)


class SittingRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        DECLINED = "declined", "Declined"
        CANCELLED = "cancelled", "Cancelled"

    owner = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="sitting_requests"
    )
    sitter = models.ForeignKey(
        PetSitter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sitting_jobs",
    )
    pets = models.ManyToManyField(Pet, related_name="sitting_requests")
    start_date = models.DateField()
    end_date = models.DateField()
    location = models.CharField(max_length=255)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    care_requirements = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )
    total_price_cents = models.PositiveIntegerField()
    commission_rate = models.DecimalField(max_digits=4, decimal_places=2, default=0.10)
    owner_rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    owner_feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="end_after_start",
            ),
        ]


class SittingUpdate(models.Model):
    request = models.ForeignKey(
        SittingRequest, on_delete=models.CASCADE, related_name="updates"
    )
    sitter = models.ForeignKey(
        PetSitter, on_delete=models.PROTECT, related_name="sitting_updates"
    )
    new_status = models.CharField(
        max_length=20, choices=SittingRequest.Status.choices, blank=True
    )
    note = models.TextField(blank=True)
    photo = models.FileField(
        storage=update_images, validators=[IMAGE_TYPES], blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
