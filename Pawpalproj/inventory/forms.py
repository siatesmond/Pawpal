from decimal import Decimal

from django import forms

from service.models import BookingUpdate, Booking, IMAGE_TYPES

from .models import Product


class StockForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "stock_quantity",
        ]


class ProductForm(forms.ModelForm):
    price_dollars = forms.DecimalField(
        label="Price (SGD)",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )

    # one tick box per care tag, saved as "skin, joint"
    care_tags = forms.MultipleChoiceField(
        label="Care tags",
        choices=Product.CARE_TAG_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Tick the health needs this product helps with. Used to recommend it to pets with these needs.",
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
            "ingredients",
            "care_tags",
            "life_stage",
        ]
        labels = {"image_url": "Product photo"}
        help_texts = {
            "ingredients": "Main ingredients, comma separated, e.g. chicken, rice. Used to hide products a pet is allergic to.",
        }
        widgets = {
            # a plain file picker; the form template shows the current photo above it
            "image_url": forms.FileInput(attrs={"accept": ".jpg,.jpeg,.png,.webp"}),
        }

    # checks if the product exists in DB and prefills with the price in dollars
    # to ensure price is displayed in dollars in the form instead of cents
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["price_dollars"] = Decimal(
                self.instance.price_cents
            ) / Decimal("100")
            self.fields["image_url"].help_text = (
                "JPG, PNG or WEBP. Leave empty to keep the current photo."
            )
            # tick the boxes for the tags already saved
            saved_tags = []
            for tag in self.instance.care_tags.split(","):
                if tag.strip():
                    saved_tags.append(tag.strip())
            self.initial["care_tags"] = saved_tags
        else:
            self.fields["image_url"].help_text = "JPG, PNG or WEBP."

    # list of ticked tags -> "skin, joint" for the text field in the database
    def clean_care_tags(self):
        return ", ".join(self.cleaned_data["care_tags"])

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_status"].choices = [
            (value, label)
            for value, label in self.fields["new_status"].choices
            if value != Booking.Status.CANCELLED # staff cannot set booking status to CANCELLED, only customers can cancel their own bookings
        ]
