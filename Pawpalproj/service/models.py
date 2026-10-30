from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q

# Create your models here.
# Service
# TimeSlot
# Booking
# BookingUpdate

IMAGE_TYPES = FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])
service_images = FileSystemStorage(
    location=settings.BASE_DIR / "service" / "static" / "service" / "images",
    base_url="/static/service/images/",
)


class Service(models.Model):
    class Category(models.TextChoices):
        GROOMING = "GROOMING", "Grooming"
        BOARDING = "BOARDING", "Boarding"
        DAYCARE = "DAYCARE", "Daycare"
        OTHER = "OTHER", "Other"

    name = models.CharField(max_length=150)
    category = models.CharField(max_length=20, choices=Category.choices)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    price_cents = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class TimeSlot(models.Model):
    outlet = models.ForeignKey(
        "core.Outlet",
        on_delete=models.PROTECT,
        related_name="time_slots",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="time_slots",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    capacity = models.PositiveIntegerField()
    booked_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["outlet", "service", "start_time"],
                name="unique_timeslot_outlet_service_start",
            ),
            models.CheckConstraint(
                condition=Q(end_time__gt=models.F("start_time")),
                name="timeslot_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(booked_count__lte=models.F("capacity")),
                name="timeslot_booked_count_lte_capacity",
            ),
            models.CheckConstraint(
                condition=Q(capacity__gte=1),
                name="timeslot_capacity_gte_one",
            ),
        ]

    def __str__(self):
        return f"{self.service.name} - {self.start_time}"


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    customer = models.ForeignKey(
        "user.Customer",
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    pet = models.ForeignKey(
        "user.Pet",
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    slot = models.ForeignKey(
        TimeSlot,
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    check_out_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    price_cents = models.PositiveIntegerField()
    points_discount_cents = models.PositiveIntegerField(default=0)
    total_cents = models.PositiveIntegerField()
    cancellation_fee_cents = models.PositiveIntegerField(default=0)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status="CANCELLED", cancelled_at__isnull=False)
                    | (~Q(status="CANCELLED") & Q(cancelled_at__isnull=True))
                ),
                name="booking_cancelled_at_matches_status",
            ),
        ]

    def __str__(self):
        return f"Booking {self.pk}"


class BookingUpdate(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="updates",
    )
    staff = models.ForeignKey(
        "user.Staff",
        on_delete=models.PROTECT,
        related_name="booking_updates",
    )
    new_status = models.CharField(
        max_length=20,
        choices=Booking.Status.choices,
    )
    note = models.TextField(blank=True)
    photo = models.FileField(
        storage=service_images, validators=[IMAGE_TYPES], blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Update for Booking {self.booking}"
