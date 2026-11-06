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
    class Meta:
        model = Product
        fields = '__all__'

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