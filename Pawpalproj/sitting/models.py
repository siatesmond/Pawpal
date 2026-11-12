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

# Models in this file:
# PetSitter       (a User who looks after pets)
# SittingRequest  (a pet owner's request, and the job once a sitter takes it)
# SittingUpdate   (status changes, notes and photos during a job)


# Allowed file types and where uploads are saved

IMAGE_TYPES = FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])
DOCUMENT_TYPES = FileExtensionValidator(
    allowed_extensions=["jpg", "jpeg", "png", "pdf"]
)

sitting_images = FileSystemStorage(
    location=settings.BASE_DIR / "sitting" / "static" / "sitting" / "images",
    base_url="/static/sitting/images/",
)

update_images = FileSystemStorage(
    location=settings.BASE_DIR / "sitting" / "static" / "update" / "images",
    base_url="/static/update/images/",
)


# Pet sitters

class PetSitter(User):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    bio = models.TextField(blank=True)
    # The sitter types only the postal code. The system looks up the map
    # position (latitude, longitude) and the area name (service_area) from it.
    postal_code = models.CharField(max_length=6, blank=True)
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
        storage=sitting_images, validators=[DOCUMENT_TYPES], blank=True
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

    @property
    def daily_rate_display(self):
        return f"{self.daily_rate_cents / 100:.2f}"


# Sitting requests and jobs

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

    # who cancelled the request and why (empty unless the status is Cancelled)
    class CancelledBy(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        SITTER = "sitter", "Pet sitter"
        PAWPAL = "pawpal", "Pawpal (business owner)"

    cancelled_by = models.CharField(max_length=20, choices=CancelledBy.choices, blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="end_after_start",
            ),
        ]

    def status_colour(self):
        # colour of the status pill: green when completed, yellow when waiting for payment
        if self.status == "completed":
            return "pill-success"
        if self.status == "pending":
            return "pill-honey"
        return "pill-outline"

    @property
    def number_of_days(self):
        # both the start and end day count, e.g. 20 Nov to 24 Nov = 5 days
        return (self.end_date - self.start_date).days + 1

    @property
    def commission_cents(self):
        # Pawpal keeps commission_rate (10%) of every sitting job
        return int(self.total_price_cents * self.commission_rate)

    @property
    def sitter_payout_cents(self):
        # what the sitter receives = job price - Pawpal commission
        return self.total_price_cents - self.commission_cents

    @property
    def total_price_display(self):
        return f"{self.total_price_cents / 100:.2f}"

    @property
    def commission_display(self):
        return f"{self.commission_cents / 100:.2f}"

    @property
    def sitter_payout_display(self):
        return f"{self.sitter_payout_cents / 100:.2f}"


# Updates during a job

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
