from decimal import Decimal

from django import forms

from service.models import BookingUpdate, IMAGE_TYPES

from .models import Product

class StockForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'stock_quantity',
        ]

class ProductForm(forms.ModelForm):
    price_dollars = forms.DecimalField(
        label="Price (SGD)",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )

    class Meta:
        model = Product
        fields = [
            "category",
            "name",
            "brand",
            "pet_type",
            "description",
            "image_url",
            "price_dollars",
            "stock_quantity",
            "low_stock_level",
            "is_active",
        ]
    # checks if the product exists in DB and prefills with the price in dollars 
    # to ensure price is displayed in dollars in the form instead of cents
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["price_dollars"] = (
                Decimal(self.instance.price_cents) / Decimal("100")
            )

    # overrides the save method to convert the price from dollars to cents before saving the product instance
    def save(self, commit=True):
        self.instance.price_cents = int(
            self.cleaned_data["price_dollars"] * Decimal("100")
        )
        return super().save(commit=commit)

class BookingUpdateForm(forms.ModelForm):
    class Meta:
        model = BookingUpdate
        fields = [
            "new_status",
            "note",
        ]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 4}),
        }