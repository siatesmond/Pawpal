from django.db import models
from django.db.models import Q

# Create your models here.
# Payment
# PointsTransaction

class Payment(models.Model):
    class Method(models.TextChoices):
        CARD = "CARD", "Card"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"
        REFUNDED = "REFUNDED", "Refunded"

    customer = models.ForeignKey(
        "user.Customer", on_delete=models.PROTECT, related_name="payments"
    )
    booking = models.ForeignKey(
        "service.Booking",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )
    order = models.ForeignKey(
        "inventory.Order",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )
    sitting_request = models.ForeignKey(
        "sitting.SittingRequest",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )
    amount_cents = models.PositiveIntegerField()
    method = models.CharField(
        max_length=20, choices=Method.choices, default=Method.CARD
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        booking__isnull=False,
                        order__isnull=True,
                        sitting_request__isnull=True,
                    )
                    | Q(
                        booking__isnull=True,
                        order__isnull=False,
                        sitting_request__isnull=True,
                    )
                    | Q(
                        booking__isnull=True,
                        order__isnull=True,
                        sitting_request__isnull=False,
                    )
                ),
                name="payment_exactly_one_target",
            ),
        ]

    def __str__(self):
        return f"Payment {self.pk} - {self.status}"
    

class PointsTransaction(models.Model):
    class Type(models.TextChoices):
        EARNED = "EARNED", "Earned"
        REDEEMED = "REDEEMED", "Redeemed"
        REFUNDED = "REFUNDED", "Refunded"

    customer = models.ForeignKey(
        "user.Customer", on_delete=models.CASCADE, related_name="points_transactions"
    )
    points = models.IntegerField()
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="points_transactions",
    )
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(transaction_type__in=["EARNED", "REFUNDED"], points__gt=0)
                    | Q(transaction_type="REDEEMED", points__lt=0)
                ),
                name="points_sign_matches_type",
            ),
        ]

    def __str__(self):
        return f"{self.transaction_type}: {self.points} points"
