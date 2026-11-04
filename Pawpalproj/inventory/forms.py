from django import forms

from .models import Product

class StockForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'stock_quantity',
        ]