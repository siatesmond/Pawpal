from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.db.models import Q
from service.models import Booking
from sitting.models import SittingRequest
from user.models import Customer

IMAGE_TYPES = FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])

review_images = FileSystemStorage(
    location=settings.BASE_DIR / "review" / "static" / "review" / "images",
    base_url="/static/review/images/",
)


# Create your models here.
# Review


class Review(models.Model):
    reviewer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="reviews"
    )
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, null=True, blank=True, related_name="reviews"
    )
    sitting_request = models.ForeignKey(
        SittingRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True)
    photo = models.FileField(
        storage=review_images, validators=[IMAGE_TYPES], blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1, rating__lte=5), name="rating_1_to_5"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        booking__isnull=False,
                        sitting_request__isnull=True,
                    )
                    | Q(
                        booking__isnull=True,
                        sitting_request__isnull=False,
                    )
                ),
                name="review_for_exactly_one_item",
            ),
        ]
