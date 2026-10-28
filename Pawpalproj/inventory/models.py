from django.db import models
from django.db.models import Q

# Create your models here.
# Category
# Brand
# Product
# Order
# OrderItem
# CartItem


class Category(models.Model):
    name = models.CharField(max_length=200, unique=True)

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=200, unique=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    class PetType(models.TextChoices):
        DOG = "DOG", "Dog"
        CAT = "CAT", "Cat"
        OTHER = "OTHER", "Other"

    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    name = models.CharField(max_length=200)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products")
    pet_type = models.CharField(max_length=20, choices=PetType.choices)
    description = models.TextField()
    image_url = models.URLField(max_length=500, blank=True)
    price_cents = models.PositiveIntegerField()
    stock_quantity = models.PositiveIntegerField(default=0)
    low_stock_level = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    customer = models.ForeignKey(
        "user.Customer", on_delete=models.PROTECT, related_name="orders"
    )
    pickup_outlet = models.ForeignKey(
        "core.Outlet",
        on_delete=models.PROTECT,
        related_name="orders",
        null=True,
        blank=True,
    )
    delivery_address = models.ForeignKey(
        "user.Address",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )
    est_delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    subtotal_cents = models.PositiveIntegerField()
    delivery_fee_cents = models.PositiveIntegerField(default=0)
    points_discount_cents = models.PositiveIntegerField(default=0)
    total_cents = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order {self.pk}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="order_items"
    )
    quantity = models.PositiveIntegerField()
    unit_price_cents = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order", "product"],
                name="unique_order_product",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="order_item_quantity_gte_one",
            ),
        ]

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"


class CartItem(models.Model):
    customer = models.ForeignKey(
        "user.Customer", on_delete=models.CASCADE, related_name="cart_items"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="cart_items"
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "product"],
                name="unique_customer_cart_product",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="cart_item_quantity_gte_one",
            ),
        ]

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
